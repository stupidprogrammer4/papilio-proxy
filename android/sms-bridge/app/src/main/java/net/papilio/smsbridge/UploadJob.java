package net.papilio.smsbridge;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.json.JSONObject;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

public final class UploadJob extends JobService {
    private static final int JOB_ID = 1;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private Future<?> active;
    private JobParameters running;
    private final android.os.Handler callbacks = new android.os.Handler(android.os.Looper.getMainLooper());
    static void schedule(Context context, BridgeSettings settings) {
        if (BridgeSettings.preferences(context).getBoolean("paused", false)) return;
        JobInfo job = new JobInfo.Builder(JOB_ID, new ComponentName(context, UploadJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPersisted(true)
            .setBackoffCriteria(settings.retrySeconds * 1000L, JobInfo.BACKOFF_POLICY_EXPONENTIAL).build();
        if (context.getSystemService(JobScheduler.class).schedule(job) != JobScheduler.RESULT_SUCCESS) BridgeSettings.preferences(context).edit().putString("status", "Android could not schedule upload; tap retry").apply();
    }
    public boolean onStartJob(JobParameters parameters) {
        running = parameters;
        active = executor.submit(() -> {
            boolean retry = false;
            try (SmsOutbox outbox = new SmsOutbox(this)) {
                BridgeSettings settings = BridgeSettings.load(this);
                for (JSONObject payload : outbox.pending(settings.batchSize)) {
                    if (Thread.currentThread().isInterrupted()) { retry = true; break; }
                    int response = upload(settings, payload);
                    if (response == 200) outbox.acknowledge(payload.getString("event_id"));
                    else if (response >= 400 && response < 500 && response != 429) {
                        BridgeSettings.preferences(this).edit().putBoolean("paused", true).putString("status", "Upload paused: API rejected this event (" + response + "). Fix enrollment or review the payment, then retry.").apply(); break;
                    } else { retry = true; break; }
                }
                if (!BridgeSettings.preferences(this).getBoolean("paused", false)) { retry = retry || outbox.count() > 0; BridgeSettings.preferences(this).edit().putString("status", retry ? "Waiting to retry pending uploads" : "All queued bank SMS acknowledged").apply(); }
            } catch (Exception error) { retry = true; BridgeSettings.preferences(this).edit().putString("status", "Network or settings error; queued SMS retained").apply(); }
            boolean reschedule = retry;
            callbacks.post(() -> {
                if (running == parameters) { running = null; jobFinished(parameters, reschedule); }
            });
        });
        return true;
    }
    public boolean onStopJob(JobParameters parameters) { running = null; if (active != null) active.cancel(true); return true; }
    public void onDestroy() { running = null; executor.shutdownNow(); super.onDestroy(); }
    private int upload(BridgeSettings settings, JSONObject payload) throws Exception {
        byte[] raw = payload.toString().getBytes(StandardCharsets.UTF_8);
        String timestamp = Long.toString(System.currentTimeMillis() / 1000);
        Mac mac = Mac.getInstance("HmacSHA256"); mac.init(new SecretKeySpec(settings.apiKey.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        mac.update((settings.deviceId + "." + timestamp + ".").getBytes(StandardCharsets.UTF_8));
        StringBuilder signature = new StringBuilder(); for (byte value : mac.doFinal(raw)) signature.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        URL url = new URL(settings.origin.replaceAll("/$", "") + "/v1/webhooks/sms-devices/" + settings.deviceId);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setInstanceFollowRedirects(false); connection.setConnectTimeout(settings.connectTimeout); connection.setReadTimeout(settings.readTimeout);
            connection.setRequestMethod("POST"); connection.setDoOutput(true); connection.setFixedLengthStreamingMode(raw.length);
            connection.setRequestProperty("Content-Type", "application/json"); connection.setRequestProperty("X-Papilio-Timestamp", timestamp); connection.setRequestProperty("X-Papilio-Signature", signature.toString());
            try (java.io.OutputStream output = connection.getOutputStream()) { output.write(raw); }
            int status = connection.getResponseCode();
            if (status == 200) {
                try (java.io.InputStream input = connection.getInputStream()) {
                    java.io.ByteArrayOutputStream response = new java.io.ByteArrayOutputStream();
                    byte[] chunk = new byte[Math.min(settings.responseLimit, settings.responseChunk)];
                    int received;
                    while ((received = input.read(chunk)) != -1) {
                        if (received > settings.responseLimit - response.size()) throw new java.io.IOException("API acknowledgement exceeds configured capacity");
                        response.write(chunk, 0, received);
                    }
                    byte[] body = response.toByteArray();
                    if (body.length > settings.responseLimit || !new JSONObject(new String(body, StandardCharsets.UTF_8)).optBoolean("accepted", false)) throw new java.io.IOException("Invalid API acknowledgement");
                }
            }
            return status;
        } finally { connection.disconnect(); }
    }
}
