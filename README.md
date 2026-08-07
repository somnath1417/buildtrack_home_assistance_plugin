# BuildTrack Home Assistant Custom Integration

## Installation Guide

This guide explains how to install and configure the BuildTrack Home Assistant Custom Integration using HACS (Home Assistant Community Store).

-----------------------------------------------------------------------------------------------

# Prerequisites

Before installing the integration, ensure the following requirements are met:

* Home Assistant is installed and running.
* HACS is installed and configured.
* You have valid BuildTrack account credentials.
* You have the required API configuration details:
  * Username
  * Password
  * Client ID
  * Client Secret
  * Application URL (`app_url`)
  * Authorization URL (`auth_url`)

-----------------------------------------------------------------------------------------------

# Step 1 – Add BuildTrack as a Custom Repository

1. Open HACS from the Home Assistant sidebar.
2. Click the ⋮ (three-dot menu) in the top-right corner.
3. Select Custom repositories.
4. Enter the BuildTrack repository URL.
5. Select:
   Category: 'Integration'
6. Click Add.

> The BuildTrack repository is now available inside HACS.

-----------------------------------------------------------------------------------------------
# Step 2 – Install the BuildTrack Integration

1. Navigate to HACS → Integrations.
2. Search for BuildTrack.
3. Open the BuildTrack integration page.
4. Click Download.
5. Wait for the installation to complete.
6. Restart Home Assistant.

> Restarting Home Assistant is required before the integration becomes available.

-----------------------------------------------------------------------------------------------
# Step 3 – Configure the Integration

1. Open:
   Settings → Devices & Services
2. Click Add Integration.
3. Search for BuildTrack.
4. Select BuildTrack from the list.
5. Complete the configuration wizard.

Provide the following information when prompted:

| Field         | Description                  |
| ------------- | ---------------------------- |
| Username      | BuildTrack account username  |
| Password      | BuildTrack account password  |
| Client ID     | OAuth Client ID              |
| Client Secret | OAuth Client Secret          |
| App URL       | BuildTrack Application URL   |
| Auth URL      | BuildTrack Authorization URL |



# Step 4 – Verify the Installation

After successful configuration:

* The BuildTrack integration appears under Settings → Devices & Services.
* Devices are discovered automatically.
* Supported entities are created, including:
  * Lights
  * Climate
  * Other supported BuildTrack devices
* Entity states are synchronized with the BuildTrack platform.

-----------------------------------------------------------------------------------------------
# Updating the Integration

When a new version is available:
1. Open HACS.
2. Navigate to Integrations.
3. Open BuildTrack.
4. Click Update.
5. Restart Home Assistant after the update completes.

-----------------------------------------------------------------------------------------------
# Troubleshooting

If the integration does not appear after installation:
* Verify that the repository was added under the Integration category.
* Confirm the repository has been downloaded successfully through HACS.
* Restart Home Assistant.
* Ensure all authentication credentials are correct.
* Verify that the App URL and Authorization URL are reachable.
* Check the Home Assistant logs for BuildTrack-related errors.

-----------------------------------------------------------------------------------------------
# Supported Features

The BuildTrack Home Assistant Integration currently supports:
* Device discovery
* Light control
* Climate control
* OAuth authentication
* Automatic entity creation
* HACS-based installation and updates

-----------------------------------------------------------------------------------------------
# Support
If you encounter issues during installation or configuration, please review the Home Assistant logs and provide the relevant BuildTrack integration logs when reporting an issue.
