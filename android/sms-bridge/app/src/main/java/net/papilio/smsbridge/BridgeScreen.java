package net.papilio.smsbridge;

import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;

/** Native presentation only: enrollment, storage and delivery belong to their owners. */
final class BridgeScreen extends LinearLayout {
    private static final int INK = 0xff20263c, MUTED = 0xff727a90;
    private static final int ACCENT = 0xff6554d9, BORDER = 0xffe6e8f1;
    private static final int BACKGROUND = 0xfff4f6fb, WHITE = 0xffffffff;
    EditText origin, device, key, senders, keywords, policy;
    private final LinearLayout content, form, footer;
    private final TextView heading, detail, badge, queued, permission;
    private final Button retryLoading, saveButton;
    private final List<Button> actions = new ArrayList<>();
    private final Runnable allowSms, retryUploads, restoreAddress;
    private boolean enrolled;

    /** Rotation-only draft; no key is written to an Android saved-state bundle. */
    static final class EnrollmentDraft {
        final String origin, device, key, senders, keywords, policy;
        EnrollmentDraft(String origin, String device, String key, String senders, String keywords, String policy) {
            this.origin = origin; this.device = device; this.key = key;
            this.senders = senders; this.keywords = keywords; this.policy = policy;
        }
    }

    EnrollmentDraft draft() {
        if (origin == null) return null;
        return new EnrollmentDraft(origin.getText().toString(), device.getText().toString(),
                key.getText().toString(), senders.getText().toString(),
                keywords.getText().toString(), policy.getText().toString());
    }

    void restoreDraft(EnrollmentDraft draft) {
        origin.setText(draft.origin); device.setText(draft.device); key.setText(draft.key);
        senders.setText(draft.senders); keywords.setText(draft.keywords); policy.setText(draft.policy);
        content.requestFocus();
    }

    BridgeScreen(Context context, Runnable save, Runnable restoreAddress, Runnable allowSms,
                 Runnable retryUploads, Runnable retryLoad) {
        super(context);
        this.allowSms = allowSms; this.retryUploads = retryUploads; this.restoreAddress = restoreAddress;
        setOrientation(VERTICAL);
        setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        setBackgroundColor(BACKGROUND);
        setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bounds = insets.getInsets(
                        WindowInsets.Type.systemBars() | WindowInsets.Type.ime()
                                | WindowInsets.Type.displayCutout());
                setPadding(bounds.left, bounds.top, bounds.right, bounds.bottom);
            } else {
                setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                        insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            }
            return insets;
        });

        ScrollView scroll = new ScrollView(context);
        scroll.setFillViewport(true);
        scroll.setClipToPadding(false);
        scroll.setVerticalScrollBarEnabled(false);
        addView(scroll, new LayoutParams(LayoutParams.MATCH_PARENT, 0, 1));
        content = column(); content.setPadding(dp(20), dp(20), dp(20), dp(12));
        content.setFocusableInTouchMode(true);
        scroll.addView(content);

        LinearLayout brand = row();
        ImageView mark = new ImageView(context);
        mark.setImageResource(R.drawable.ic_papilio);
        mark.setContentDescription("Papilio butterfly logo");
        mark.setBackground(shape(ACCENT, 16, ACCENT));
        brand.addView(mark, new LayoutParams(dp(50), dp(50)));
        LinearLayout name = column();
        name.setPadding(dp(12), 0, 0, 0);
        name.addView(text("Papilio", 22, INK, true));
        TextView subtitle = text("SMS BRIDGE", 10, MUTED, true);
        subtitle.setLetterSpacing(0.15f); name.addView(subtitle);
        brand.addView(name, new LayoutParams(0, LayoutParams.WRAP_CONTENT, 1));
        TextView local = text("PRIVATE", 9, ACCENT, true);
        local.setPadding(dp(10), dp(7), dp(10), dp(7));
        local.setBackground(shape(0xffeeebff, 10, 0xffeeebff));
        local.setLetterSpacing(0.06f); brand.addView(local);
        content.addView(brand); space(content, 22);

        LinearLayout hero = column(); hero.setPadding(dp(20), dp(20), dp(20), dp(20));
        GradientDrawable heroBackground = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{0xff252b49, 0xff363265});
        heroBackground.setCornerRadius(dp(26)); hero.setBackground(heroBackground);
        badge = text("LOADING", 10, 0xffc7bfff, true);
        badge.setLetterSpacing(0.12f); hero.addView(badge); space(hero, 10);
        heading = text("Your payment companion", 24, WHITE, true); hero.addView(heading);
        space(hero, 8);
        detail = text("Loading your encrypted enrollment…", 13, 0xffc0c5d8, false);
        detail.setLineSpacing(dp(3), 1); hero.addView(detail); space(hero, 20);
        LinearLayout metrics = row();
        LinearLayout queue = column(); queued = text("—", 25, WHITE, true);
        queue.addView(queued); queue.addView(text("Pending messages", 11, 0xffb8bed3, false));
        metrics.addView(queue, new LayoutParams(0, LayoutParams.WRAP_CONTENT, 1));
        View divider = new View(context); divider.setBackgroundColor(0xff41465b);
        LayoutParams separator = new LayoutParams(dp(1), dp(46));
        separator.setMargins(0, 0, dp(20), 0); metrics.addView(divider, separator);
        LinearLayout access = column(); permission = text("Checking", 16, WHITE, true);
        access.addView(permission); space(access, 5);
        access.addView(text("SMS permission", 11, 0xffb8bed3, false));
        metrics.addView(access, new LayoutParams(0, LayoutParams.WRAP_CONTENT, 1));
        hero.addView(metrics); space(hero, 18);
        TextView security = text("SIGNED DELIVERY  /  ENCRYPTED STORAGE", 9, 0xffc7bfff, true);
        security.setLetterSpacing(0.08f); hero.addView(security);
        content.addView(hero); space(content, 24);
        content.addView(text("Bridge settings", 20, INK, true)); space(content, 5);
        content.addView(text("Your connection. Your delivery rules.", 12, MUTED, false)); space(content, 16);

        form = column(); content.addView(form);
        retryLoading = action("Retry loading enrollment", false, retryLoad);
        retryLoading.setVisibility(GONE); form.addView(retryLoading);

        footer = column(); footer.setPadding(dp(20), dp(12), dp(20), dp(12));
        footer.setBackgroundColor(WHITE);
        saveButton = action("Save enrollment  →", true, save);
        footer.addView(saveButton, new LayoutParams(LayoutParams.MATCH_PARENT, dp(52)));
        TextView note = text("Encrypted on this phone · HTTPS delivery", 10, MUTED, false);
        note.setGravity(Gravity.CENTER); note.setPadding(0, dp(8), 0, 0); footer.addView(note);
        footer.setVisibility(GONE); addView(footer);
        content.requestFocus();
    }

    void showEnrollment(JSONObject current, String defaultOrigin) {
        form.removeAllViews();
        actions.removeIf(action -> action != saveButton && action != retryLoading);
        enrolled = current.has("device_id") && !current.optString("api_key").isEmpty();
        LinearLayout connection = card("01", "Connect your panel", "Use the enrollment created in your admin panel.");
        origin = field(connection, "API address", current.optString("origin"),
                "Your deployed HTTPS address", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        space(connection, 9);
        TextView defaultAddress = text("Default: " + defaultOrigin
                + (defaultOrigin.endsWith(".example") ? " · sample address" : ""), 11, MUTED, false);
        connection.addView(defaultAddress); space(connection, 8);
        connection.addView(action("Use default address", false, restoreAddress));
        device = field(connection, "Device ID", current.optString("device_id"),
                "Enrolled phone identifier", InputType.TYPE_CLASS_NUMBER);
        key = field(connection, "Enrollment key", "", enrolled ? "Saved securely · leave blank to keep" : "Paste your private API key",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        key.setSaveEnabled(false); key.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        form.addView(connection); space(form, 16);

        LinearLayout bank = card("02", "Choose bank messages", "Only exact sender names and matching credit text are forwarded.");
        senders = field(bank, "Bank sender IDs", joined(current.optJSONArray("senders")),
                "Exact sender names, separated by commas", InputType.TYPE_CLASS_TEXT);
        keywords = field(bank, "Credit keywords", joined(current.optJSONArray("credit_keywords")),
                "Keywords, separated by commas", InputType.TYPE_CLASS_TEXT);
        space(bank, 14);
        Button allow = action("Allow incoming SMS", false, allowSms);
        bank.addView(allow, new LayoutParams(LayoutParams.MATCH_PARENT, dp(48)));
        TextView inbox = text("Existing SMS inbox is never read.", 11, MUTED, false);
        inbox.setPadding(0, dp(10), 0, 0); bank.addView(inbox);
        form.addView(bank); space(form, 16);

        LinearLayout delivery = card("03", "Delivery & retries", "Control upload limits, timeouts and recovery.");
        JSONObject advanced = new JSONObject();
        for (String name : new String[]{"connect_timeout_ms", "read_timeout_ms", "retry_seconds",
                "batch_size", "queue_capacity", "response_limit_bytes", "response_chunk_bytes"}) {
            try { if (current.has(name)) advanced.put(name, current.get(name)); }
            catch (org.json.JSONException ignored) { /* Known fields retain their saved values. */ }
        }
        LinearLayout advancedBody = column();
        String encoded;
        try { encoded = advanced.toString(2); } catch (org.json.JSONException error) { encoded = advanced.toString(); }
        policy = field(advancedBody, "Delivery settings · JSON", encoded, "",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        policy.setTypeface(Typeface.MONOSPACE); policy.setTextSize(12);
        advancedBody.setVisibility(GONE);
        Button toggle = action("Show advanced settings  +", false, () -> {});
        toggle.setOnClickListener(view -> {
            boolean opening = advancedBody.getVisibility() != VISIBLE;
            advancedBody.setVisibility(opening ? VISIBLE : GONE);
            toggle.setText(opening ? "Hide advanced settings  −" : "Show advanced settings  +");
        });
        space(delivery, 14); delivery.addView(toggle); delivery.addView(advancedBody);
        space(delivery, 10);
        Button retry = action("Retry pending uploads", false, retryUploads);
        delivery.addView(retry); form.addView(delivery); space(form, 8);
        footer.setVisibility(VISIBLE);
        content.requestFocus();
    }

    void showLoadFailure() {
        badge.setText("STORAGE UNAVAILABLE"); heading.setText("Your settings are retained");
        detail.setText("We couldn't open encrypted storage. Try again when phone storage is available.");
        retryLoading.setEnabled(true); retryLoading.setVisibility(VISIBLE);
    }

    void showStatus(int count, boolean smsAllowed, boolean paused, String status) {
        queued.setText(Integer.toString(count));
        permission.setText(smsAllowed ? "Granted" : "Not allowed");
        permission.setTextColor(smsAllowed ? 0xff9be0c9 : 0xffffd697);
        badge.setText(paused ? "UPLOADS PAUSED" : enrolled ? "ENROLLMENT SAVED" : "SETUP REQUIRED");
        heading.setText(paused ? "Review your connection" : enrolled ? "Your bridge, at a glance" : "Let's connect your phone");
        detail.setText(enrolled ? status : "Add your panel details and allow SMS access to get started.");
    }

    void showMessage(String message) { detail.setText(message); }

    void setSaving(boolean saving) {
        for (Button action : actions) action.setEnabled(!saving);
        for (EditText input : new EditText[]{origin, device, key, senders, keywords, policy}) input.setEnabled(!saving);
        saveButton.setText(saving ? "Saving securely…" : "Save enrollment  →");
    }

    void enrollmentSaved() { enrolled = true; key.setText(""); }

    private LinearLayout card(String number, String title, String description) {
        LinearLayout card = column(); card.setPadding(dp(18), dp(18), dp(18), dp(18));
        card.setBackground(shape(WHITE, 20, BORDER));
        LinearLayout titleRow = row();
        TextView step = text(number, 10, ACCENT, true); step.setGravity(Gravity.CENTER);
        step.setBackground(shape(0xffeeebff, 9, 0xffeeebff));
        titleRow.addView(step, new LayoutParams(dp(30), dp(30)));
        TextView heading = text(title, 17, INK, true); heading.setPadding(dp(10), 0, 0, 0);
        titleRow.addView(heading); card.addView(titleRow); space(card, 8);
        TextView help = text(description, 12, MUTED, false); help.setLineSpacing(dp(2), 1);
        card.addView(help); return card;
    }

    private EditText field(LinearLayout parent, String name, String value, String hint, int type) {
        space(parent, 16); parent.addView(text(name, 12, INK, true)); space(parent, 7);
        EditText field = new EditText(getContext()); field.setId(View.generateViewId());
        field.setInputType(type); field.setSingleLine((type & InputType.TYPE_TEXT_FLAG_MULTI_LINE) == 0);
        field.setTextSize(14); field.setTextColor(INK); field.setHintTextColor(MUTED);
        field.setHint(hint); field.setText(value); field.setSelectAllOnFocus(false);
        field.setPadding(dp(12), dp(12), dp(12), dp(12)); field.setMinHeight(dp(49));
        field.setBackground(shape(0xfff8f8fc, 12, BORDER));
        parent.addView(field, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));
        return field;
    }

    private Button action(String title, boolean primary, Runnable callback) {
        Button button = new Button(getContext()); button.setAllCaps(false);
        button.setText(title); button.setTextSize(13); button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setTextColor(primary ? WHITE : ACCENT); button.setMinHeight(dp(48));
        button.setPadding(dp(12), dp(8), dp(12), dp(8));
        button.setBackground(new android.graphics.drawable.RippleDrawable(
                android.content.res.ColorStateList.valueOf(primary ? 0xff8e80ef : 0xffded8ff),
                shape(primary ? ACCENT : 0xfff1eeff, 12, primary ? ACCENT : 0xfff1eeff), null));
        button.setOnClickListener(view -> callback.run()); actions.add(button); return button;
    }

    private TextView text(String value, float size, int color, boolean bold) {
        TextView view = new TextView(getContext()); view.setText(value); view.setTextSize(size);
        view.setTextColor(color); view.setTypeface(Typeface.create("sans-serif", bold ? Typeface.BOLD : Typeface.NORMAL));
        return view;
    }
    private LinearLayout column() { LinearLayout view = new LinearLayout(getContext()); view.setOrientation(VERTICAL); return view; }
    private LinearLayout row() { LinearLayout view = new LinearLayout(getContext()); view.setOrientation(HORIZONTAL); view.setGravity(Gravity.CENTER_VERTICAL); return view; }
    private void space(LinearLayout parent, int height) { parent.addView(new View(getContext()), new LayoutParams(1, dp(height))); }
    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private GradientDrawable shape(int fill, int radius, int stroke) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(fill);
        shape.setCornerRadius(dp(radius)); shape.setStroke(dp(1), stroke); return shape;
    }
    private String joined(JSONArray values) {
        if (values == null) return "";
        List<String> result = new ArrayList<>();
        for (int index = 0; index < values.length(); index++) result.add(values.optString(index));
        return String.join(", ", result);
    }
}
