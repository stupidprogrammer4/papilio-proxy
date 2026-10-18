# Using Papilio

[فارسی](user-guide.fa.md) · [Installation](getting-started.en.md) · [Project](../README.md)

## Language and appearance

The controls above the workspace select English or Persian and Light, Dark or
System appearance. System follows your browser's operating-system preference.
Selections are saved in that browser; clearing browser storage resets them.
If storage is unavailable, the current selection still works and a notice explains
that it cannot be saved.

Persian sets RTL and English sets LTR. Sign-in, overview and workspace navigation have
translations. Translation of the remaining forms, help text and error catalogue
is still being completed; some content remains English.

## Start with a receiving destination and a plan

1. Review administrator scopes and business settings.
2. In Payments, create a receiving card, IBAN or bank account. Check its owner,
   active state and applicable payment method.
3. In Plans & bundles, create a plan with quota and duration, quota without expiry,
   or duration with unlimited data. Set a price and the intended configuration bundle.
4. Review delivery requirements before making the plan available. Configuration
   exports and a ready node are different states; validate the intended runtime.

## Register a node, core and configuration

1. In **Nodes**, register a unique code, display name, public address, port and
   protocol. The agent key is shown only once; store it securely. This form records
   the node and does not install VPN software or start a service on that server.
2. Open **Cores** from the node row and record a core type, code and display name.
   An unobserved state means no runtime report has arrived for that core; it does
   not prove that the core is running.
3. In **Configurations**, create a configuration for that node and core. Enter the
   protocol, port, listen address, TLS and transport to match the software already
   installed. Complete the WireGuard or OpenVPN fields when using those protocols.
4. Review the saved settings JSON and full server JSON, then run a suitable check in
   **Connection lab**. An exported file alone does not prove client connectivity,
   applied settings or core health.
5. Before enabling sales, check node status, runtime observation, delivery profile
   and an actual client connection separately. Installing a node from this page is
   not available yet.

## Edit bot text and menu

In **Settings**, choose a text locale, edit the welcome message and button labels,
and search the catalog for other phrases. One revision saves the changes for all
locales in the same form. The welcome image must use a public HTTPS URL. Turning a
button off hides its existing flow from the menu.

The Telegram token is not stored in panel settings; manage it only as a deployment
file secret. After saving, verify the presentation through the bot itself. A
successful save or build does not prove that Telegram received a message.

## Customer subscription page

With a private subscription link, a customer can review usage and expiry, retrieve
configuration or a QR code, and open client app guidance for their operating system.
Share the link only with that customer and rotate it if exposed. Per-node ping
measurement has not been implemented yet, so the page does not invent latency data.

## Follow a purchase

The customer chooses a plan and funding method. A wallet purchase needs sufficient
balance. Payment-funded checkout supplies captured receiving details and an exact
rial amount. Confirm the destination and displayed amount on that invoice.

After settlement approval, the whole approved transfer credits the wallet; the
plan price is charged by the purchase workflow. In the optional four-digit mode,
an amount adjustment remains wallet credit. In ordinary payment mode there is no
four-digit matching requirement.

A purchased order can still await provisioning or manually supplied profiles.
Check both purchase and delivery status before telling the customer that access
works. Recover an existing paid attempt instead of charging for another purchase.

## Manual review and SMS approval

For manual approval, verify funds against the receiving account, then review the
corresponding request. A receipt image alone does not establish settlement.

To receive SMS evidence, enroll a phone for a particular destination and configure
exact sender filters and a parser for the bank's credit format. Test a new incoming
SMS; the Android app does not import the existing inbox. Receiving an SMS or OCR
receipt alone does not prove a trusted bank deposit. Any automatic matching decision
must use an approved trusted source; review ambiguous evidence manually.

Four-digit payment identifiers are optional. When enabled, customers must transfer
the exact displayed **rial** amount without rounding. Do not send a general bank
instruction when a checkout already has its own captured instruction.

## Renewal, discounts and automation

Review auto-renewal eligibility, wallet balance and the customer's selected policy.
Set loyalty thresholds, unlimited-plan volume equivalents and discount rules in
their respective settings; they are business choices, not fixed pricing.

In Automation, review enabled or paused state, cadence, capacity and recent
outcomes. Queue publication is not completion: check committed business results.

## Configuration editing and troubleshooting

Review saved-settings JSON and full server JSON in their respective editors.
Check protocol, core version, routing and node assignment before applying a change.
An exported JSON document is not proof that the target client can connect.

If a payment remains pending, inspect destination, exact amount, device validity,
sender, bank parser and evidence state. If delivery remains pending, inspect the
subscription's provisioning result and assigned runtime. For TLS problems, check
hostname, DNS and certificate trust. Keep secret-bearing evidence out of public issues.

Use [deployment](deployment.md), [feature reference](feature-reference.en.md) and
[testing](testing.md) for detailed setup, contracts and verification boundaries.
