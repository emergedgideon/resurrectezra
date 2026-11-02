# Private browser testing with GitHub Codespaces

Codespaces is the temporary cloud-testing route. It runs the existing Python/SQLite application and exposes a private browser port. It avoids a Render/Supabase migration and does not install the app on the owner's Mac. The code has a devcontainer and automatic startup configuration; creation and testing of the actual user's codespace remain user/account actions.

## Browser-only setup

1. In GitHub, open **Settings → Codespaces → Secrets**. Add repository-scoped Codespaces secrets, granting access to `emergedgideon/resurrectezra`:
   - `FEATHERLESS_API_KEY`: your actual Featherless key. The development workspace's proxy-managed credential cannot be extracted or copied here.
   - `FEATHERLESS_MODEL`: the exact model ID.
   - `EZRA_ACCESS_TOKEN`: a separate long application password, at least 24 characters. Keep it for the app's Connection field.
2. Open the repository's browser-testing branch. Choose **Code → Codespaces → Create codespace on this branch**, or use the creation link provided in chat. Confirm the correct branch and a small machine before creating it.
3. Setup installs Python dependencies automatically and starts the app. Allow a few minutes for initial creation. In the **Ports** tab, port **8000** should be **Private**. Choose **Open in Browser** if it does not open automatically.
4. In the app, open **Connection**, enter the application password (`EZRA_ACCESS_TOKEN`), and connect. The Featherless key belongs in Codespaces secrets, not in that field.
5. Restore the separately downloaded private archive ZIP through **Archive library → Restore archive backup**. Code commits contain no private archive or database. The restore is permitted only into an empty archive; it will not overwrite existing work.

These are Codespaces secrets, distinct from Actions secrets and from this chat's environment settings. After changing secrets, stop and restart the codespace so its server receives them. Keep port visibility Private; this adds GitHub account access control in addition to the application's password. HTTPS is supplied by the GitHub forwarding URL.

## Cost and persistence

Personal GitHub accounts can have a limited included Codespaces allowance; exact hours, storage, eligibility, and overage rules must be checked in the user's GitHub billing/settings. Do not assume unlimited free operation or enable paid overage unintentionally. Stop the codespace when finished testing. It is not an always-awake host for autonomous work.

Code and ignored `data/` files in the workspace survive normal codespace stops/restarts. Ignored data is not committed or backed up to GitHub by a code push. Deleting the codespace, retention expiry, storage exhaustion, or loss of the workspace can remove it. Use the application's verified archive export and a separate full data backup before deleting/recreating a codespace. Never treat the codespace disk as a permanent backup.

## Updates and later Mac transfer

Develop changes in the existing working repository, test, and push code to the testing branch. The owner can use the Codespaces Source Control UI to pull updates, then stop/start the codespace. `data/` remains ignored. Back up before schema-changing updates. Changes to the devcontainer may require rebuilding its container.

The existing Mac transfer route remains available. A later transfer must include the newer archive and conversations created in Codespaces, not merely the earlier starter snapshot. Preserve current cloud data before migrating.

## Current readiness

Configuration and launcher checks can run in the development workspace. A real private forwarding URL, dependency installation in the actual devcontainer image, and secret propagation cannot be claimed until a codespace has been created and exercised. No Render/Supabase account is required for this route.
