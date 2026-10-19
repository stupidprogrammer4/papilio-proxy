package net.papilio.smsbridge;

import android.Manifest;
import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import java.io.ByteArrayOutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.json.JSONObject;

public final class UploadJob extends JobService {
    private static final int UPLOAD_JOB_ID = 1;
    private static final int STATUS_JOB_ID = 2;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler callbacks = new Handler(Looper.getMainLooper());
    private final ConcurrentHashMap<JobParameters, Future<?>> active =
            new ConcurrentHashMap<>();

    static void schedule(Context context, BridgeSettings settings) {
        scheduleUpload(context, settings);
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (scheduler.getPendingJob(STATUS_JOB_ID) == null) {
            JobInfo status = new JobInfo.Builder(
                    STATUS_JOB_ID, new ComponentName(context, UploadJob.class))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setPersisted(true)
                    .setPeriodic(settings.statusIntervalMinutes * 60 * 1000L)
                    .build();
            scheduler.schedule(status);
        }
    }

    static void scheduleUpload(Context context, BridgeSettings settings) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        JobInfo upload = new JobInfo.Builder(
                UPLOAD_JOB_ID, new ComponentName(context, UploadJob.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPersisted(true)
                .setBackoffCriteria(
                        settings.retrySeconds * 1000L,
                        JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                .build();
        if (scheduler.schedule(upload) != JobScheduler.RESULT_SUCCESS) {
            status(context, "retrying", "Android could not schedule upload; tap retry", "job_schedule_failed");
        }
    }

    @Override
    public boolean onStartJob(JobParameters parameters) {
        boolean statusOnly = parameters.getJobId() == STATUS_JOB_ID;
        Future<?> work = executor.submit(() -> run(parameters, statusOnly));
        active.put(parameters, work);
        return true;
    }

    private void run(JobParameters parameters, boolean statusOnly) {
        boolean retry = false;
        String state = "retrying";
        BridgeSettings settings = null;
        Integer pendingCount = null;
        try {
            settings = BridgeSettings.load(this);
            boolean paused = BridgeSettings.preferences(this)
                    .getBoolean("paused", false);
            if (!statusOnly && !paused) {
                retry = uploadPending(settings);
                paused = BridgeSettings.preferences(this)
                        .getBoolean("paused", false);
            }
            try (SmsOutbox outbox = new SmsOutbox(this)) {
                pendingCount = outbox.count();
            }
            state = deliveryState(paused, retry, pendingCount, settings);
            String errorCode = deliveryErrorCode(state, retry);
            status(this, state, statusMessage(state, pendingCount), errorCode);
            try {
                if (!reportStatus(settings, pendingCount, state)) {
                    status(this, state, "Status API rejected the device report", "api_unavailable");
                    retry = true;
                }
            } catch (Exception networkError) {
                status(this, state, "Status API could not be reached", "network_unavailable");
                retry = true;
            }
        } catch (Exception error) {
            state = "storage_error";
            String errorCode = settings == null
                    ? "settings_invalid" : "local_storage";
            status(this, state, "Queue or settings error; pending messages were retained", errorCode);
            if (settings != null) {
                try {
                    if (!reportStatus(settings, null, state)) {
                        retry = true;
                    }
                } catch (Exception ignored) {
                    retry = true;
                }
            }
            retry = true;
        }
        finish(parameters, retry);
    }

    private boolean uploadPending(BridgeSettings settings) throws Exception {
        boolean retry = false;
        try (SmsOutbox outbox = new SmsOutbox(this)) {
            for (JSONObject payload : outbox.pending(settings.batchSize)) {
                if (Thread.currentThread().isInterrupted()) {
                    retry = true;
                    break;
                }
                int response;
                try {
                    response = post(
                            settings,
                            "/v1/webhooks/sms-devices/" + settings.deviceId,
                            payload);
                } catch (Exception networkError) {
                    retry = true;
                    break;
                }
                if (response == 200) {
                    String eventId = payload.getString("event_id");
                    outbox.acknowledge(eventId);
                    BridgeSettings.preferences(this).edit()
                            .putString("last_acknowledged_event_id", eventId)
                            .apply();
                    continue;
                }
                if (response >= 400 && response < 500 && response != 429) {
                    BridgeSettings.preferences(this).edit()
                            .putBoolean("paused", true)
                            .apply();
                    break;
                }
                retry = true;
                break;
            }
        }
        return retry;
    }

    private boolean reportStatus(
            BridgeSettings settings, Integer pendingCount, String state)
            throws Exception {
        boolean permissionGranted = checkSelfPermission(Manifest.permission.RECEIVE_SMS)
                == PackageManager.PERMISSION_GRANTED;
        String acknowledged = BridgeSettings.preferences(this)
                .getString("last_acknowledged_event_id", null);
        JSONObject report = new JSONObject()
                .put("pending_event_count", pendingCount == null
                        ? JSONObject.NULL : pendingCount)
                .put("permission_granted", permissionGranted)
                .put("delivery_state", state)
                .put("last_acknowledged_event_id", acknowledged == null
                        ? JSONObject.NULL : acknowledged)
                .put("last_error_code", errorCode());
        int response = post(
                settings,
                "/v1/webhooks/sms-devices/" + settings.deviceId + "/status",
                report);
        return response == 200;
    }

    private int post(
            BridgeSettings settings, String path, JSONObject payload)
            throws Exception {
        byte[] raw = payload.toString().getBytes(StandardCharsets.UTF_8);
        String timestamp = Long.toString(System.currentTimeMillis() / 1000);
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(
                settings.apiKey.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        mac.update((settings.deviceId + "." + timestamp + ".")
                .getBytes(StandardCharsets.UTF_8));
        String signature = hex(mac.doFinal(raw));

        URL url = new URL(settings.origin.replaceAll("/$", "") + path);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(settings.connectTimeout);
            connection.setReadTimeout(settings.readTimeout);
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setFixedLengthStreamingMode(raw.length);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("X-Papilio-Timestamp", timestamp);
            connection.setRequestProperty("X-Papilio-Signature", signature);
            try (java.io.OutputStream output = connection.getOutputStream()) {
                output.write(raw);
            }
            int response = connection.getResponseCode();
            if (response == 200) {
                try (java.io.InputStream input = connection.getInputStream()) {
                    byte[] body = readBounded(input, settings);
                    if (!new JSONObject(new String(body, StandardCharsets.UTF_8))
                            .optBoolean("accepted", false)) {
                        throw new java.io.IOException(
                                "Invalid API acknowledgement");
                    }
                }
            }
            return response;
        } finally {
            connection.disconnect();
        }
    }

    private byte[] readBounded(
            java.io.InputStream input, BridgeSettings settings) throws Exception {
        ByteArrayOutputStream response = new ByteArrayOutputStream();
        byte[] chunk = new byte[Math.min(
                settings.responseLimit, settings.responseChunk)];
        int received;
        while ((received = input.read(chunk)) != -1) {
            if (received > settings.responseLimit - response.size()) {
                throw new java.io.IOException(
                        "API acknowledgement exceeds configured capacity");
            }
            response.write(chunk, 0, received);
        }
        return response.toByteArray();
    }

    private String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            result.append(String.format(
                    java.util.Locale.ROOT, "%02x", value & 255));
        }
        return result.toString();
    }

    private String deliveryState(
            boolean paused, boolean retry, int pendingCount,
            BridgeSettings settings) {
        if (paused) return "paused";
        if (pendingCount >= settings.queueCapacity) return "queue_full";
        if (retry || pendingCount > 0) return "retrying";
        return "ready";
    }

    private String statusMessage(String state, int pendingCount) {
        if ("paused".equals(state)) {
            return "Uploads are paused after an API rejection. Review and retry.";
        }
        if ("retrying".equals(state)) {
            return "Waiting to retry pending uploads";
        }
        if ("queue_full".equals(state)) {
            return "Local queue is full. Review the connection before more SMS arrive.";
        }
        return pendingCount == 0
                ? "All queued bank SMS acknowledged"
                : "Pending bank SMS remain in the encrypted local queue";
    }

    private String deliveryErrorCode(String state, boolean retry) {
        if ("paused".equals(state)) return "api_rejected";
        if ("queue_full".equals(state)) return "queue_capacity";
        if (retry) return "network_unavailable";
        return null;
    }

    private Object errorCode() {
        String value = BridgeSettings.preferences(this)
                .getString("last_error_code", null);
        return value == null ? JSONObject.NULL : value;
    }

    private static void status(
            Context context, String state, String message, String errorCode) {
        android.content.SharedPreferences.Editor update =
                BridgeSettings.preferences(context).edit()
                        .putString("delivery_state", state)
                        .putString("status", message);
        if (errorCode == null) {
            update.remove("last_error_code");
        } else {
            update.putString("last_error_code", errorCode);
        }
        update.apply();
    }

    private void finish(JobParameters parameters, boolean retry) {
        callbacks.post(() -> {
            Future<?> completed = active.remove(parameters);
            if (completed != null) {
                jobFinished(parameters, retry);
            }
        });
    }

    @Override
    public boolean onStopJob(JobParameters parameters) {
        Future<?> work = active.remove(parameters);
        if (work != null) {
            work.cancel(true);
        }
        return true;
    }

    @Override
    public void onDestroy() {
        active.values().forEach(work -> work.cancel(true));
        active.clear();
        executor.shutdownNow();
        super.onDestroy();
    }
}
