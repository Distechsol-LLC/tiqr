# TiQR Web: User Guide

This guide explains how to use the TiQR web app in a browser. It covers signing in, the three
roles, and the everyday tasks: issuing tickets, sending badges to print, assigning tickets, and
managing accounts, ticket types and visitor types.

## 1. Opening the app

Your administrator will give you an address such as `https://tiqr.example.com:7102/tiqr/`
(or `http://127.0.0.1:7102/tiqr/` on the server itself). Opening the bare address without
`/tiqr/` takes you to the same place.

Use a current version of Chrome, Edge, Firefox or Safari.

## 2. Signing in

1. Enter your **Username** and **Password**.
2. Select **Sign in**.

If the sign-in fails, the app shows a message:

- **Invalid username or password.** Check the spelling and try again.
- **Too many failed sign-ins.** Wait the time shown (up to 15 minutes) before trying again.
- **Your session has ended.** Sign in again.

You are signed out automatically after **30 minutes** without activity, and in any case after
**12 hours**. Your account can also be signed out by an administrator or a manager if it is
deactivated or its password is reset; sign in again with the new password when asked.

On the sign-in page, the globe button changes the language and the sun/moon button changes the
theme (light or dark).

## 3. Finding your way around

After signing in, you land on the **Tickets** page. The left-hand menu shows the pages you can use.
Select the arrow at the bottom of the menu to collapse it to icons only, and select it again to expand it.

At the top right of the screen:

- **Language**: switch the interface language.
- **Theme**: switch between light and dark.
- **Account menu**: shows your name and role, and contains **Sign out**.

## 4. Roles and what you can do

Your role decides which menu items you see. Your role is shown in the account menu.

| Menu item | Operator | Manager | Admin |
|---|:---:|:---:|:---:|
| Tickets | Yes (assigned to you only) | Yes (all tickets) | Yes (all tickets) |
| Users | No | Yes (operators only) | Yes (all roles) |
| Ticket types | No (used when creating tickets) | Yes | Yes |
| Active hours (on Tickets) | No | Yes | Yes |
| Visitor types | No (used when creating tickets) | Yes | Yes |
| Overview | No | Yes | Yes |
| BioStar | No | No | Yes |
| License | No | No | Yes |

The tasks below say which role can do each one.

## 5. Tickets

The **Tickets** page lists tickets. Each row shows the serial number, visitor, state, validity,
usage, prints, uses, price and assignee.

### Ticket states

- **Issued**: valid and waiting for its first passage. Only issued tickets can be downloaded or printed.
- **Passed**: has been used at least once and is still within its validity period.
- **Expired**: past its validity period.

### Searching and filtering

- Type in the **Search tickets** box to find a ticket by its serial number, visitor name or other details.
- Use the **Filter by state** tabs to show **All**, **Issued**, **Passed** or **Expired** tickets.
- Use the page controls at the bottom to change the number of **Rows** and move between pages.

Operators see only tickets assigned to them. Managers and admins see every ticket.

### Creating a ticket (Operator, Manager, Admin)

1. Select **New Ticket**.
2. Fill in the form:
   - **Visitor type**: choose from the list. Discounts for the visitor type are applied automatically.
   - **Ticket type**: choose from the list. The price comes from the ticket type.
   - **Usage**: **One-time** (one passage) or **Group** (one QR code for a whole group).
   - **People in the group**: for a group ticket, how many people it admits, from 2 to 100.
   - **Valid from** and **Valid until**: pick the date and time. The end must not be before the start.
3. Check the **Price**, **Discount** and **Total** shown on the form. A group pays the price once
   per person, so the form also shows the number of **People**.
4. Select **Create**.

Tickets carry no visitor name. A group ticket lets that many people through, one passage each, and
then stops; the Stats page counts it once per person. The ticket prints on a narrow slip for small
cut paper.

The new ticket is assigned to you, the account that created it. A confirmation message shows the
serial number and the visitor type.

### Creating a badge (badge mode)

In badge mode the app says **badge** wherever it would say ticket. Select **New Badge**, enter the
**Visitor name** and **Visitor type**, pick the validity, and select **Create**. Badges have no
ticket types, prices or discounts, and are always multi-use: they let their visitor through as
often as needed within the validity period. They print on a foldable A4 sheet.

If the form says **Ticket and visitor types not loaded**, ask a manager or admin to check that the
ticket types and visitor types exist, then select **Refresh** and try again.

### Printing and downloading a badge

Each ticket can produce a foldable A4 badge with the visitor's name, visitor type, validity, a QR code
and the readable serial number.

For an issued ticket, the row actions offer:

- **Download** (or **Download badge for …**): saves the PDF to your computer. Open it and print it on your own printer.
- **Print PDF** (or **Print PDF of badge …**): opens the badge in your browser's print dialog, so you can choose your own printer.
- **Send to printer** (or **Send badge … to the printer**): prints on the server's default printer. This option appears only when the administrator has turned on server printing.

Download and print are available only for **issued** tickets. Every time a badge is generated
or printed, the **Prints** count goes up, so the count shows how many badges have been made for
that ticket. Passed or expired tickets cannot be printed.

### Assigning a ticket (Manager, Admin)

1. Find the ticket and select **Assign** (or **Assign …** with the serial number).
2. Pick an account from **Assignee**.
3. Select **Assign**.

The assignee is the person responsible for the ticket. Operators see a ticket only while it is
assigned to them, and only that operator can then download or print it. Deactivated accounts cannot
hold tickets; a manager must reassign them.

## 6. Users (Manager and Admin)

The **Users** page lists sign-in accounts with their role and status.

### Adding an account

1. Select **New User**.
2. Enter a **Username** and an initial **Password**.
3. Choose a **Role** (admins only; managers can add operators only).
4. Select **Create**.

### Managers

- Add operators and deactivate or reactivate them.

### Admins

- Change an account's role with the role menu.
- Reset a password with **Reset password**. Enter the new password twice. The account is signed out
  everywhere and must sign in with the new password.
- Deactivate or reactivate an account with the status control.
- Delete an account with **Delete**. You can delete only accounts that are already deactivated and have
  never created or held a ticket.

Some rules protect everyone:

- You cannot change your own role or deactivate yourself.
- The last active admin cannot be demoted or deactivated, so there is always someone who can manage accounts.
- A deactivated account keeps its history but cannot sign in or be assigned tickets.

## 7. Ticket types and visitor types (Manager and Admin)

Operators cannot open these pages, but the ticket form uses these lists, so operators can pick from them when creating tickets.

### Ticket types

Ticket types define what a visitor pays and how much.

- **New Ticket Type**: enter a **Name**, a **Price** such as `12.50`, and a **Currency**. Select **Create**.
- **Edit**: change the name, price or currency.
- **Delete**: removes the ticket type for good. Tickets already issued keep their original price.

### Active hours

Active hours limit when tickets can be created. Select the clock icon beside **Refresh** on the Tickets (or Badges) page, then:

- Set the **From** and **To** times. A new system starts at 09:00 to 17:00. Times are in the server's timezone.
- A **To** time before the **From** time runs past midnight, so 22:00 to 06:00 covers the night.
- Clear both times and select **Save** to allow tickets at any time again.

Outside the hours, the server refuses new tickets, for operators as well as managers and admins. Tickets already issued are not affected.

### Visitor types

Visitor types define discounts. In badge mode they have no discount, only a name.

- **New Visitor Type**: enter a **Name** and a **Discount, %** as a whole number from 0 to 100. Select **Create**.
- **Edit**: change the name or discount.
- **Delete**: removes the visitor type for good. Tickets already issued keep their original discount.

## 8. Overview (Manager and Admin)

The **Overview** page shows ticket statistics for a period.

- Choose the **Period**: **Day**, **Month**, **Year**, **Range** (pick a start and end date) or **All time**.
  Use **Earlier** and **Later** to move through periods.
- The table shows these figures:
  - **Total**: every ticket issued in the period.
  - **Issued**: tickets waiting for their first passage.
  - **Passed**: tickets used at least once that are still valid.
  - **Expired**: tickets past their validity.
  - **Uses**: granted passages applied to tickets.
  - **Prints**: badges rendered or printed.

Two maintenance buttons talk to BioStar:

- **Sync** (**Pull new access events**): fetches the latest passages from the access system. Use it
  if the figures look out of date. A message reports how many new events were applied.
- **Clean** (**Remove finished tickets**): removes finished tickets from BioStar. A message reports how many were removed.

## 9. BioStar (Admin)

The **BioStar** page connects TiQR to the BioStar access system. Until it is connected, tickets stay
local and no passages are synced.

### Connecting

1. Enter the **BioStar URL**, a **Username** and a **Password** for the BioStar account TiQR should use.
2. Leave **Verify the HTTPS certificate** ticked unless your administrator tells you otherwise.
3. Select **Save and connect**.

When the settings are already saved, the button reads **Save BioStar settings** and the password field
shows that a password is kept. Leave the password blank to keep it. To stop using BioStar, select
**Disconnect**.

### Readers

Once connected, the **Readers** table lists the access readers BioStar reports, with their ID, name,
address and status. Tick the readers TiQR should use, then save the settings. Select **Refresh** to
reload the list.

### Scan log

The **Scan log** shows the latest scans with the time, reader, direction and whether access was
**Granted** or **Denied**. Select **Refresh** to update it.

If the page cannot load the settings, readers or scan log, select **Refresh** and check that the BioStar
address is reachable from the server.

## 10. License (Admin)

The app needs an active license before it can manage tickets. If the license is missing, expired or
cannot be verified, a red message appears at the top of the License page, and the app stays locked until
a valid license is activated.

- **Request code**: a code appears in the grey box. Select **Copy** and send the code to your vendor,
  who decides whether this install gets a trial or a paid license. Anyone can request a code, but only an admin can
  activate a key.
- **License key**: paste the key your vendor sends back and select **Activate license**.
- **Machine ID**: shown at the bottom of the page. Your vendor needs it to issue a key.
- **Status**: shows whether the license is **Active**, a **Trial**, **Expired** or **Not verified**, the
  **Licensed to** name and the expiry date.

Messages you may see:

- **This key is not valid for this product.** Check you copied the whole key from the vendor.
- **This key was issued for another machine.** The key belongs to a different installation. Ask the vendor for a key using this install's request code.
- **This key has already expired.** Ask the vendor for a renewal.
- **A trial cannot replace a paid license.** Activate the paid key instead of requesting a trial.

If you are an operator or manager and see the license message, send the request code to your administrator.

## 11. Settings (Admin)

**Mode** chooses what this install issues:

- **Tickets**: one-time or group tickets without names, on small cut paper, with prices.
- **Badges**: named, multi-use visitor badges on a foldable A4 sheet, without prices.

Select the other mode and confirm with **Switch**. Each mode keeps its own tickets or badges, types
and statistics, and switching back shows them again. Accounts, the license and the active hours are
shared, so nobody has to sign in again. If the page says the mode is set on the server, ask whoever
runs the server to change `TIQR_MODE` there.

## 12. Troubleshooting

| What you see | What to do |
|---|---|
| **Cannot reach the server.** | Check your network connection, then select **Refresh** or reload the page. If it persists, tell your administrator. |
| **Something went wrong on the server.** | Try again in a moment. If it keeps happening, tell your administrator. |
| **Your session has ended.** | Sign in again. Unsaved form entries may need to be re-entered. |
| **Tickets not loaded** / **Accounts not loaded** | Select **Refresh**. If the message stays, check the connection. |
| The **Send to printer** option is missing | Server printing is not enabled. Use **Download** or **Print PDF** instead. |
| A badge does not print | Make sure the ticket is **Issued**, then try **Print PDF** or **Download** and print from your own computer. |
| Page not found | Use the menu to go back to a page you can access, or select **Back home**. |

When you report a problem, include the serial number of the ticket (if any), the page you were on and the
exact message shown.
