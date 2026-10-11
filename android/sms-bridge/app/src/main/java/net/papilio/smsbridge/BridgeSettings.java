package net.papilio.smsbridge;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;

final class BridgeSettings {
    final String origin, apiKey; final long deviceId;
    final List<String> senders, creditKeywords;
    final int connectTimeout, readTimeout, retrySeconds, batchSize, queueCapacity, responseLimit, responseChunk;
    BridgeSettings(JSONObject source) throws Exception {
        origin = source.getString("origin"); deviceId = source.getLong("device_id"); apiKey = source.getString("api_key");
        URI uri = URI.create(origin);
        if (!"https".equals(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null || !(uri.getPath().isEmpty() || "/".equals(uri.getPath()))) throw new IllegalArgumentException("Enter an HTTPS API origin without a path");
        if (deviceId <= 0 || apiKey.length() < 32) throw new IllegalArgumentException("Device ID and enrollment API key are required");
        senders = strings(source.getJSONArray("senders")); creditKeywords = strings(source.getJSONArray("credit_keywords"));
        connectTimeout = source.getInt("connect_timeout_ms"); readTimeout = source.getInt("read_timeout_ms"); retrySeconds = source.getInt("retry_seconds"); batchSize = source.getInt("batch_size"); queueCapacity = source.getInt("queue_capacity"); responseLimit = source.getInt("response_limit_bytes"); responseChunk = source.getInt("response_chunk_bytes");
        if (senders.isEmpty() || creditKeywords.isEmpty() || connectTimeout <= 0 || readTimeout <= 0 || retrySeconds <= 0 || batchSize <= 0 || queueCapacity <= 0 || responseLimit <= 0 || responseChunk <= 0) throw new IllegalArgumentException("Sender, credit filters and positive delivery capacities are required");
    }
    static List<String> strings(JSONArray values) throws Exception {
        java.util.ArrayList<String> result = new java.util.ArrayList<>();
        for (int i = 0; i < values.length(); i++) { String value = values.getString(i).trim(); if (!value.isEmpty()) result.add(value); }
        return result;
    }
    static SharedPreferences preferences(Context context) { return context.getSharedPreferences("bridge", Context.MODE_PRIVATE); }
    static JSONObject editable(Context context) throws Exception {
        JSONObject defaults;
        try (java.io.InputStream stream = context.getAssets().open("defaults.json")) { defaults = new JSONObject(new String(read(stream), StandardCharsets.UTF_8)); }
        String encrypted = preferences(context).getString("settings", null);
        if (encrypted == null) return defaults;
        JSONObject saved = new JSONObject(SecretVault.decrypt(encrypted));
        java.util.Iterator<String> names = defaults.keys();
        while (names.hasNext()) { String name = names.next(); if (!saved.has(name)) saved.put(name, defaults.get(name)); }
        return saved;
    }
    private static byte[] read(java.io.InputStream input) throws Exception {
        java.io.ByteArrayOutputStream result = new java.io.ByteArrayOutputStream();
        try (java.io.BufferedInputStream buffered = new java.io.BufferedInputStream(input)) {
            int next; while ((next = buffered.read()) != -1) result.write(next);
        }
        return result.toByteArray();
    }
    static BridgeSettings load(Context context) throws Exception { return new BridgeSettings(editable(context)); }
    static void save(Context context, JSONObject value) throws Exception {
        new BridgeSettings(value);
        if (!preferences(context).edit().putString("settings", SecretVault.encrypt(value.toString())).putBoolean("paused", false).commit()) throw new java.io.IOException("Could not persist settings");
    }
    boolean accepts(String sender, String body) { return senders.contains(sender) && creditKeywords.stream().anyMatch(body::contains); }
}
