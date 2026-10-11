package net.papilio.smsbridge.tests;

import android.app.Instrumentation;
import android.os.Bundle;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLException;
import org.json.JSONObject;

/** Exercises the installed target app's Android TLS policy without sending SMS. */
public final class LocalHttpsInstrumentation extends Instrumentation {
    private Bundle arguments;

    @Override public void onCreate(Bundle arguments) {
        this.arguments = arguments;
        start();
    }

    @Override public void onStart() {
        new Thread(() -> {
            Bundle result = new Bundle();
            try {
                String origin = arguments.getString("origin");
                int timeout = Integer.parseInt(arguments.getString("timeout_ms"));
                int capacity = Integer.parseInt(arguments.getString("response_capacity"));
                URL trusted = new URL(origin + "/healthz");
                if (!trusted.getProtocol().equals("https") || !trusted.getHost().equals("localhost")
                        || timeout <= 0 || capacity <= 0) throw new IllegalArgumentException();
                HttpsURLConnection connection = (HttpsURLConnection) trusted.openConnection();
                try {
                    connection.setInstanceFollowRedirects(false);
                    connection.setConnectTimeout(timeout); connection.setReadTimeout(timeout);
                    if (connection.getResponseCode() != 200) throw new AssertionError();
                    byte[] body;
                    try (java.io.InputStream input = connection.getInputStream()) {
                        body = input.readNBytes(capacity + 1);
                    }
                    if (body.length > capacity || !new JSONObject(new String(body,
                            java.nio.charset.StandardCharsets.UTF_8)).getString("status").equals("ok")) {
                        throw new AssertionError();
                    }
                } finally { connection.disconnect(); }
                result.putString("trusted_localhost_health", "passed");

                URL untrusted = new URL("https", "127.0.0.1", trusted.getPort(), "/healthz");
                HttpsURLConnection other = (HttpsURLConnection) untrusted.openConnection();
                boolean rejected = false;
                try {
                    other.setConnectTimeout(timeout); other.setReadTimeout(timeout);
                    other.getResponseCode();
                } catch (SSLException expected) { rejected = true; }
                finally { other.disconnect(); }
                if (!rejected) throw new AssertionError();
                result.putString("other_host_local_ca", "rejected");
                finish(-1, result);
            } catch (Exception | AssertionError error) {
                result.putString("failure_type", error.getClass().getSimpleName());
                finish(0, result);
            }
        }, "local-tls-check").start();
    }
}
