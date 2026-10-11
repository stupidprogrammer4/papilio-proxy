package net.papilio.smsbridge.tests;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.json.JSONObject;

/** Apply authorized local enrollment through the real form and encrypted save. */
public final class EnrollPhoneInstrumentation extends Instrumentation {
    private Bundle arguments;
    @Override public void onCreate(Bundle arguments) { this.arguments = arguments; start(); }
    @Override public void onStart() {
        new Thread(() -> {
            Bundle result = new Bundle();
            try {
                String file = arguments.getString("enrollment_file");
                if (file == null || !file.matches("/data/local/tmp/papilio-enrollment-[a-f0-9]+\\.json")) {
                    throw new IllegalArgumentException();
                }
                int limit = Integer.parseInt(arguments.getString("input_capacity"));
                int timeout = Integer.parseInt(arguments.getString("wait_ms"));
                if (limit <= 0 || timeout <= 0) throw new IllegalArgumentException();
                byte[] bytes;
                try (ParcelFileDescriptor descriptor = getUiAutomation().executeShellCommand("cat " + file);
                     java.io.InputStream input = new ParcelFileDescriptor.AutoCloseInputStream(descriptor)) {
                    bytes = input.readNBytes(limit + 1);
                }
                if (bytes.length > limit) throw new IllegalArgumentException();
                JSONObject values = new JSONObject(new String(bytes, java.nio.charset.StandardCharsets.UTF_8));
                Activity activity = startActivitySync(new Intent(Intent.ACTION_MAIN)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        .setComponent(new ComponentName("net.papilio.smsbridge", "net.papilio.smsbridge.MainActivity")));
                View root = activity.getWindow().getDecorView();
                await(root, "form", timeout);
                runOnMainSync(() -> {
                    try {
                        field(root, "API address").setText(values.getString("origin"));
                        field(root, "Device ID").setText(Long.toString(values.getLong("device_id")));
                        field(root, "Enrollment key").setText(values.getString("api_key"));
                        field(root, "Bank sender IDs").setText(joined(values.getJSONArray("senders")));
                        field(root, "Credit keywords").setText(joined(values.getJSONArray("credit_keywords")));
                        Button save = button(root, "Save enrollment  →");
                        if (save == null || !save.performClick()) throw new IllegalStateException();
                    } catch (Exception error) { throw new IllegalStateException("Enrollment form failed"); }
                });
                await(root, "saved", timeout);
                result.putString("native_enrollment_save", "passed");
                finish(-1, result);
            } catch (Exception | AssertionError error) {
                result.putString("failure_type", error.getClass().getSimpleName());
                finish(0, result);
            }
        }, "local-enrollment").start();
    }
    private void await(View root, String state, int timeout) throws InterruptedException {
        long deadline = SystemClock.elapsedRealtime() + timeout;
        AtomicBoolean ready = new AtomicBoolean();
        while (SystemClock.elapsedRealtime() < deadline) {
            runOnMainSync(() -> ready.set(state.equals("form")
                    ? root.findViewWithTag("Enrollment key") != null
                    : hasText(root, "ENROLLMENT SAVED") && field(root, "Enrollment key").length() == 0));
            if (ready.get()) return;
            Thread.sleep(25);
        }
        throw new AssertionError();
    }
    private EditText field(View root, String label) { return (EditText) root.findViewWithTag(label); }
    private String joined(JSONArray values) throws org.json.JSONException {
        java.util.ArrayList<String> names = new java.util.ArrayList<>();
        for (int i = 0; i < values.length(); i++) names.add(values.getString(i));
        return String.join(", ", names);
    }
    private Button button(View root, String text) {
        if (root instanceof Button && ((Button) root).getText().toString().equals(text)) return (Button) root;
        if (root instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) root;
            for (int i = 0; i < group.getChildCount(); i++) {
                Button found = button(group.getChildAt(i), text); if (found != null) return found;
            }
        }
        return null;
    }
    private boolean hasText(View root, String text) {
        if (root instanceof TextView && ((TextView) root).getText().toString().equals(text)) return true;
        if (root instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) root;
            for (int i = 0; i < group.getChildCount(); i++) if (hasText(group.getChildAt(i), text)) return true;
        }
        return false;
    }
}
