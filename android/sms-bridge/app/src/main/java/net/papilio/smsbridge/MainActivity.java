package net.papilio.smsbridge;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.os.Bundle;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Owns lifecycle and actions; BridgeScreen owns the native presentation. */
public final class MainActivity extends Activity {
    private BridgeScreen screen;
    private JSONObject current;
    private final ExecutorService storage = Executors.newSingleThreadExecutor();
    private boolean destroyed;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        screen = new BridgeScreen(this, this::save,
                () -> requestPermissions(new String[]{Manifest.permission.RECEIVE_SMS}, 1),
                this::retryUploads, this::loadEnrollment);
        setContentView(screen);
        loadEnrollment();
    }

    private void loadEnrollment() {
        storage.execute(() -> {
            try {
                JSONObject enrollment = BridgeSettings.editable(this);
                runOnUiThread(() -> {
                    if (!destroyed) {
                        current = enrollment;
                        screen.showEnrollment(enrollment);
                        Object retained = getLastNonConfigurationInstance();
                        if (retained instanceof BridgeScreen.EnrollmentDraft) {
                            screen.restoreDraft((BridgeScreen.EnrollmentDraft) retained);
                        }
                        showStatus();
                    }
                });
            } catch (Exception error) {
                runOnUiThread(() -> { if (!destroyed) screen.showLoadFailure(); });
            }
        });
    }

    private void save() {
        try {
            JSONObject value = new JSONObject(screen.policy.getText().toString());
            value.put("origin", screen.origin.getText().toString().trim());
            value.put("device_id", Long.parseLong(screen.device.getText().toString().trim()));
            value.put("api_key", screen.key.getText().length() == 0
                    ? current.optString("api_key") : screen.key.getText().toString().trim());
            value.put("senders", list(screen.senders.getText().toString()));
            value.put("credit_keywords", list(screen.keywords.getText().toString()));
            BridgeSettings validated = new BridgeSettings(value);
            JSONObject previous = current;
            screen.setSaving(true);
            storage.execute(() -> {
                try {
                    try (SmsOutbox outbox = new SmsOutbox(this)) {
                        if (outbox.count() > 0 && previous.has("device_id")
                                && (previous.getLong("device_id") != validated.deviceId
                                || !previous.getString("origin").equals(validated.origin))) {
                            throw new IllegalArgumentException(
                                    "Finish pending uploads before changing the device or API address.");
                        }
                    }
                    BridgeSettings.save(this, value);
                    UploadJob.schedule(this, validated);
                    runOnUiThread(() -> {
                        if (!destroyed) {
                            current = value;
                            screen.enrollmentSaved();
                            screen.setSaving(false);
                        }
                    });
                    refreshStatus();
                } catch (Exception error) {
                    display("Settings weren't saved. " + error.getMessage());
                    runOnUiThread(() -> { if (!destroyed) screen.setSaving(false); });
                }
            });
        } catch (NumberFormatException error) {
            screen.showMessage("Enter the numeric device ID from your admin panel. Your draft is retained.");
            screen.device.requestFocus();
        } catch (Exception error) {
            screen.showMessage("Settings weren't saved. " + error.getMessage());
        }
    }

    private void retryUploads() {
        storage.execute(() -> {
            try {
                BridgeSettings settings = BridgeSettings.load(this);
                BridgeSettings.preferences(this).edit().putBoolean("paused", false).apply();
                UploadJob.schedule(this, settings);
                refreshStatus();
            } catch (Exception error) { display("Save a valid enrollment before retrying uploads."); }
        });
    }

    private JSONArray list(String input) {
        JSONArray result = new JSONArray();
        for (String value : input.split(",")) if (!value.trim().isEmpty()) result.put(value.trim());
        return result;
    }
    private void display(String text) {
        runOnUiThread(() -> { if (!destroyed) screen.showMessage(text); });
    }
    private void showStatus() { storage.execute(this::refreshStatus); }
    private void refreshStatus() {
        try (SmsOutbox outbox = new SmsOutbox(this)) {
            int count = outbox.count();
            boolean paused = BridgeSettings.preferences(this).getBoolean("paused", false);
            String status = BridgeSettings.preferences(this).getString("status", "Enrollment saved. Waiting for matching bank SMS.");
            runOnUiThread(() -> {
                if (!destroyed) screen.showStatus(count,
                        checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED,
                        paused, status);
            });
        } catch (Exception error) { display("Couldn't read the queue. Pending messages are retained."); }
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == 1 && current != null) showStatus();
    }
    @Override public void onResume() {
        super.onResume();
        if (screen != null && current != null) showStatus();
    }
    @Override public Object onRetainNonConfigurationInstance() { return screen.draft(); }
    @Override public void onDestroy() { destroyed = true; storage.shutdown(); super.onDestroy(); }
}
