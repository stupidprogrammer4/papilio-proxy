package net.papilio.smsbridge;

import android.content.Context;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;

final class SmsOutbox extends SQLiteOpenHelper {
    static final class CapacityException extends IllegalStateException {
        private static final long serialVersionUID = 1L;

        CapacityException(String message) {
            super(message);
        }
    }

    SmsOutbox(Context context) { super(context, "sms-outbox.db", null, 1); }
    public void onCreate(SQLiteDatabase db) { db.execSQL("CREATE TABLE messages(event_id TEXT PRIMARY KEY,payload TEXT NOT NULL,created_at INTEGER NOT NULL)"); }
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { throw new IllegalStateException("Explicit outbox migration required"); }
    synchronized void enqueue(JSONObject payload, int capacity) throws Exception {
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            String event = payload.getString("event_id");
            try (Cursor existing = db.query("messages", new String[]{"event_id"}, "event_id=?", new String[]{event}, null, null, null)) { if (existing.moveToFirst()) { db.setTransactionSuccessful(); return; } }
            try (Cursor count = db.rawQuery("SELECT count(*) FROM messages", null)) { count.moveToFirst(); if (count.getInt(0) >= capacity) throw new CapacityException("Outbox full; review the connection before more bank SMS arrive"); }
            ContentValues values = new ContentValues(); values.put("event_id", event); values.put("payload", SecretVault.encrypt(payload.toString())); values.put("created_at", System.currentTimeMillis());
            db.insertOrThrow("messages", null, values); db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    List<JSONObject> pending(int limit) throws Exception {
        List<JSONObject> result = new ArrayList<>();
        try (Cursor rows = getReadableDatabase().query("messages", new String[]{"payload"}, null, null, null, null, "created_at,event_id", String.valueOf(limit))) {
            while (rows.moveToNext()) result.add(new JSONObject(SecretVault.decrypt(rows.getString(0))));
        }
        return result;
    }
    void acknowledge(String event) { getWritableDatabase().delete("messages", "event_id=?", new String[]{event}); }
    int count() { try (Cursor result = getReadableDatabase().rawQuery("SELECT count(*) FROM messages", null)) { result.moveToFirst(); return result.getInt(0); } }
}
