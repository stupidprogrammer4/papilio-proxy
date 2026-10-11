package net.papilio.smsbridge;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.text.InputType;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.ArrayList;
import java.util.List;
import android.widget.*;
import org.json.JSONArray;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private LinearLayout content; private TextView status; private EditText origin, device, key, senders, keywords, policy;
    private JSONObject current;
    private final ExecutorService storage = Executors.newSingleThreadExecutor();
    private final List<Button> actions = new ArrayList<>();
    private boolean destroyed;
    private Button retryLoading;
    public void onCreate(Bundle state) {
        super.onCreate(state); ScrollView scroll = new ScrollView(this); content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(28, 48, 28, 32); content.setBackgroundColor(0xfff5f6fa); scroll.addView(content); setContentView(scroll);
        TextView title = label("Papilio SMS Bridge"); title.setTextSize(28); label("Forward enrolled bank-credit SMS to your Papilio API. Pending messages and the API key stay encrypted on this phone.");
        status = label("Loading encrypted enrollment…");
        retryLoading = new Button(this); retryLoading.setText("Retry loading enrollment");
        retryLoading.setOnClickListener(view -> loadEnrollment()); content.addView(retryLoading);
        loadEnrollment();
    }
    private void loadEnrollment() {
        retryLoading.setEnabled(false);
        storage.execute(() -> {
            try {
                JSONObject enrollment = BridgeSettings.editable(this);
                runOnUiThread(() -> { if (!destroyed) { current = enrollment; content.removeView(retryLoading); buildForm(); } });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    if (!destroyed) { status.setText("Could not load encrypted enrollment. Saved settings were retained; retry when device storage is available."); retryLoading.setEnabled(true); }
                });
            }
        });
    }
    private void buildForm() {
        content.removeView(status);
        origin = field("HTTPS API origin", current.optString("origin"), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        device = field("Enrolled device ID", current.has("device_id") ? current.optString("device_id") : "", InputType.TYPE_CLASS_NUMBER);
        key = field("API key (leave blank to retain saved key)", "", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        senders = field("Exact bank sender IDs, separated by commas", joined(current.optJSONArray("senders")), InputType.TYPE_CLASS_TEXT);
        keywords = field("Credit-message keywords, separated by commas", joined(current.optJSONArray("credit_keywords")), InputType.TYPE_CLASS_TEXT);
        JSONObject advanced = new JSONObject();
        for (String name : new String[]{"connect_timeout_ms", "read_timeout_ms", "retry_seconds", "batch_size", "queue_capacity", "response_limit_bytes", "response_chunk_bytes"}) { try { if (current.has(name)) advanced.put(name, current.get(name)); } catch (Exception ignored) {} }
        policy = field("Advanced delivery settings (JSON)", advanced.toString(), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        button("Save enrollment", this::save); button("Allow incoming SMS", () -> requestPermissions(new String[]{Manifest.permission.RECEIVE_SMS}, 1)); button("Retry pending uploads", () -> {
            storage.execute(() -> {
                BridgeSettings.preferences(this).edit().putBoolean("paused", false).apply();
                try { UploadJob.schedule(this, BridgeSettings.load(this)); refreshStatus(); }
                catch (Exception error) { display("Save a valid enrollment first"); }
            });
        });
        status = label(""); showStatus();
    }
    private void save() {
        try {
            JSONObject value = new JSONObject(policy.getText().toString()); value.put("origin", origin.getText().toString().trim()); value.put("device_id", Long.parseLong(device.getText().toString().trim()));
            value.put("api_key", key.getText().length() == 0 ? current.optString("api_key") : key.getText().toString().trim());
            value.put("senders", list(senders)); value.put("credit_keywords", list(keywords));
            BridgeSettings validated = new BridgeSettings(value);
            JSONObject previous = current;
            setActionsEnabled(false);
            storage.execute(() -> {
                try {
                    try (SmsOutbox outbox = new SmsOutbox(this)) {
                        if (outbox.count() > 0 && previous.has("device_id") && (previous.getLong("device_id") != validated.deviceId || !previous.getString("origin").equals(validated.origin))) throw new IllegalArgumentException("Finish pending uploads before changing the device or API origin");
                    }
                    BridgeSettings.save(this, value);
                    UploadJob.schedule(this, validated);
                    runOnUiThread(() -> { if (!destroyed) { current = value; key.setText(""); setActionsEnabled(true); } });
                    refreshStatus();
                } catch (Exception error) {
                    display("Settings were not saved: " + error.getMessage());
                    runOnUiThread(() -> { if (!destroyed) setActionsEnabled(true); });
                }
            });
        } catch (Exception error) { status.setText("Settings were not saved: " + error.getMessage()); }
    }
    private JSONArray list(EditText input) { JSONArray result = new JSONArray(); for (String value : input.getText().toString().split(",")) if (!value.trim().isEmpty()) result.put(value.trim()); return result; }
    private String joined(JSONArray values) { if (values == null) return ""; java.util.ArrayList<String> result = new java.util.ArrayList<>(); for (int i = 0; i < values.length(); i++) result.add(values.optString(i)); return String.join(", ", result); }
    private TextView label(String text) { TextView view = new TextView(this); view.setText(text); view.setTextColor(0xff20243a); view.setPadding(0, 12, 0, 12); content.addView(view); return view; }
    private EditText field(String name, String value, int type) { label(name); EditText input = new EditText(this); input.setInputType(type); input.setText(value); input.setSingleLine((type & InputType.TYPE_TEXT_FLAG_MULTI_LINE) == 0); content.addView(input); return input; }
    private void button(String text, Runnable action) { Button button = new Button(this); button.setText(text); button.setOnClickListener(view -> action.run()); content.addView(button); actions.add(button); }
    private void setActionsEnabled(boolean enabled) {
        for (Button action : actions) action.setEnabled(enabled);
        for (EditText input : new EditText[]{origin, device, key, senders, keywords, policy}) input.setEnabled(enabled);
    }
    private void display(String text) { runOnUiThread(() -> { if (!destroyed) status.setText(text); }); }
    private void showStatus() { storage.execute(this::refreshStatus); }
    private void refreshStatus() {
        try (SmsOutbox outbox = new SmsOutbox(this)) {
            String detail = "\nQueued events: " + outbox.count() + "\n" + BridgeSettings.preferences(this).getString("status", "Ready for enrollment");
            runOnUiThread(() -> { if (!destroyed) status.setText((checkSelfPermission(Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED ? "SMS permission granted" : "SMS permission required") + detail); });
        } catch (Exception error) { display("Could not read outbox status; queued SMS retained"); }
    }
    public void onResume() { super.onResume(); if (status != null && current != null) showStatus(); }
    public void onDestroy() { destroyed = true; storage.shutdown(); super.onDestroy(); }
}
