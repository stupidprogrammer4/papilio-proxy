package net.papilio.smsbridge;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;

public final class BankSmsReceiver extends BroadcastReceiver {
    public void onReceive(Context context, Intent intent) {
        if (!Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction())) return;
        SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent);
        if (parts.length == 0) return;
        PendingResult pending = goAsync();
        new Thread(() -> {
            try {
                BridgeSettings settings = BridgeSettings.load(context);
                String sender = parts[0].getOriginatingAddress(); long sentAt = parts[0].getTimestampMillis();
                StringBuilder body = new StringBuilder();
                for (SmsMessage part : parts) { if (!java.util.Objects.equals(sender, part.getOriginatingAddress())) throw new IllegalArgumentException("Mixed SMS sender"); body.append(part.getMessageBody()); }
                if (!settings.accepts(sender, body.toString())) return;
                String identity = settings.deviceId + "\n" + sender + "\n" + sentAt + "\n" + body;
                byte[] digest = MessageDigest.getInstance("SHA-256").digest(identity.getBytes(StandardCharsets.UTF_8));
                StringBuilder event = new StringBuilder(); for (byte value : digest) event.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
                JSONObject origin = new JSONObject()
                        .put("kind", "direct_sms")
                        .put("original_provider_timestamp_ms", sentAt)
                        .put("canonicalization_revision", 1)
                        .put("original_sender", sender);
                JSONObject payload = new JSONObject().put("event_id", event.toString()).put("sender", sender).put("message", body.toString()).put("sent_at", Instant.ofEpochMilli(sentAt).toString()).put("origin", origin);
                try (SmsOutbox outbox = new SmsOutbox(context)) { outbox.enqueue(payload, settings.queueCapacity); }
                UploadJob.schedule(context, settings);
                BridgeSettings.preferences(context).edit().putString("status", "Bank SMS queued").apply();
            } catch (Exception error) { BridgeSettings.preferences(context).edit().putString("status", "Could not queue SMS; inspect settings and storage").apply(); }
            finally { pending.finish(); }
        }, "papilio-sms-receive").start();
    }
}
