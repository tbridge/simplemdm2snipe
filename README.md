# simplemdm2snipe

## About

This `python3` script leverages the [SimpleMDM](https://simplemdm.com) and [Snipe-IT](https://snipeitapp.com) APIs to accomplish two things:
* Sync device details from SimpleMDM to Snipe-IT
* Sync asset tags from Snipe-IT to SimpleMDM.

## Overview:
simplemdm2snipe is designed to sync assets between your SimpleMDM and Snipe-IT instances. The tool searches for assets based on the serial number, not the existing asset tag. If assets exist in SimpleMDM and are not in Snipe-IT, the tool will create an asset and try to match it with an existing Snipe-IT model. This match is based on the device's model identifier (ex. MacBookAir7,1) being entered as the model number in Snipe-IT, rather than the model name. If a matching model isn't found, it will create one.

When an asset is first created, it will fill out only the most basic information. If the asset already exists in your Snipe-IT inventory, the tool will sync the information you specify in the settings.conf file and make sure that the asset tag in SimpleMDM matches the asset tag in Snipe-IT, where Snipe-IT's asset tag for that device is considered the authority.

If the asset tag field is blank in SimpleMDM when the record is being created in Snipe-IT, the script will create an asset tag with `SIMPLEMDM-$SERIAL_NUMBER` unless you enable `use_custom_pattern` in your `settings.conf` file.

## Requirements:

- Python3
- Python dependencies - Can be installed using the included `requirements.txt` using the command `python3 -m pip install -r requirements.txt` or individually using the commands `python3 -m pip install requests` and `python3 -m pip install pytz`.
- A [SimpleMDM API token](https://api.simplemdm.com) with the following permissions:
  - Custom Attributes
    - read
  - Devices
    - write
  - Device Groups
    - read
- A [Snipe-IT API key](https://snipe-it.readme.io/reference#generating-api-tokens) for a user with the following permissions:
  - Assets
    - View
    - Create
    - Edit
    - Checkin
    - Checkout
  - Users
    - View
  - Models
    - View
    - Create
    - Edit
  - Self
    - Two-Factor Authentication *(recommended, but not required)*
    - Create API Keys

## Configuration - settings.conf:

All of the keys highlighted in **bold** below are *required* in your `settings.conf` file. Please review the [settings.conf.example](https://github.com/grokability/simplemdm2snipe/blob/main/settings.conf.example) file for example settings and additional details.

Note: do not add `""` or `''` around any values.

API tokens can also be provided via environment variables for additional security.
```bash
export SIMPLEMDM_APITOKEN=simplemdm-api-key-here
export SNIPE_APIKEY=snipe-api-key-here
```

**[simplemdm]**

- **`apitoken`**: Your [SimpleMDM API token](https://a.simplemdm.com/admin/api)
- **`asset_tag_attribute`**: The custom attribute that's used to associate an asset tag with a device, for example **asset_tag**
- **`username_attribute`**: The custom attribute that's used to associate a user name to a device, for example **username**

**[snipe-it]**

- **`url`**: The base URL for your Snipe-IT instance (ie https://snipeit.example.com)
- **`apikey`**: Your [Snipe-IT API key](https://snipe-it.readme.io/reference#generating-api-tokens)
- **`time_zone`**: The time zone that your Snipe-IT instance is set to.  Refer to `APP_TIMEZONE=` in your Snipe-IT .env file.
- **`manufacturer_id`**: The manufacturer database field id for Apple in your Snipe-IT instance.
- **`defaultStatus`**: The status database field id to assign to new assets created in Snipe-IT from SimpleMDM. Typically you will want to pick a status like "Ready To Deploy".
- **`mac_model_category_id`**: The ID of the category you want to assign to Mac computers. You will have to create this in Snipe-IT and note the Category ID.
- **`iphone_model_category_id`**: The ID of the category you want to assign to iPhones. You will have to create this in Snipe-IT and note the Category ID.
- **`ipad_model_category_id`**: The ID of the category you want to assign to iPads. You will have to create this in Snipe-IT and note the Category ID.
- **`appletv_model_category_id`**: The ID of the category you want to assign to Apple TVs. You will have to create this in Snipe-IT and note the Category ID.
- `mac_custom_fieldset_id`: The ID of the category you want to assign to Mac computers. You will have to create this in Snipe-IT and note the Category ID.
- `iphone_custom_fieldset_id`: The ID of the category you want to assign to iPhones. You will have to create this in Snipe-IT and note the Category ID.
- `ipad_custom_fieldset_id`: The ID of the category you want to assign to iPads. You will have to create this in Snipe-IT and note the Category ID.
- `appletv_custom_fieldset_id`: The ID of the category you want to assign to Apple TVs. You will have to create this in Snipe-IT and note the Category ID.


**[asset-tag]**
- **`use_custom_pattern`**: Set to **yes** to set your own patterns, if set to **no**, devices with no existing asset tag in SimpleMDM will default to `SIMPLEMDM-$SERIAL_NUMBER`.
- `pattern_mac`: The pattern to use when creating new Macs in Snipe-IT that do not have an asset tag in SimpleMDM.
- `pattern_iphone`: The pattern to use when creating new iPhones in Snipe-IT that do not have an asset tag in SimpleMDM.
- `pattern_ipad`: The pattern to use when creating new iPads in Snipe-IT that do not have an asset tag in SimpleMDM.
- `pattern_appletv`: The pattern to use when creating new Apple TVs in Snipe-IT that do not have an asset tag in SimpleMDM.

<br>

>**Note:** <br>
>The following sections require custom fields to be created in Snipe-IT. Please see the [API Mapping](#api-mapping) section for details.

**[mac-api-mapping]**

**[iphone-api-mapping]**

**[ipad-api-mapping]**

**[appletv-api-mapping]**


  
### API Mapping

To get the database fields for Snipe-IT Custom Fields, go to Settings and then Custom Fields inside of your Snipe-IT instance, scroll down past Fieldsets to Custom Fields, click the column selection button and make sure the 'DB Field' checkbox is checked. Copy and paste the DB Field name for Snipe-IT under *platform*-api-mapping sections in your `settings.conf` file.

To get the API mapping fields for SimpleMDM, refer to SimpleMDM's [Devices](https://api.simplemdm.com/#devices) API example.

Some example API mappings can be found below:

- MAC Address:		`_snipeit_<your_mac_address_custom_field_id> = attributes wifi_mac`
- OS Version:		`_snipeit_<your_os_version_field_id> = attributes os_version`
- Device Group: `_snipeit_<your_device_group_id> = relationships device_group id`
- Processor Architecture:		`_snipeit_<your_cpu_arch_custom_field_id>_ = attributes processor_architecture`
- FileVault Status:		`_snipeit_<your_filevault_enabled_custom_field_id> = attributes filevault_enabled`
- SimpleMDM Device ID:			`_snipeit_<your_device_id_custom_field_id> = id`

You need to set the `manufacturer_id` for Apple devices in the `settings.conf` file. You can grab the `manufacturer_id` in Snipe-IT by going to Manufacturers > click the column selection button > select the `ID` checkbox.

## Usage
```
usage: simplemdm2snipe [-h] [-l] [-v] [-d] [--dryrun] [--version] [--auto_incrementing] [--do_not_update_simplemdm] [--do_not_verify_ssl] [-r] [-f] [-u] [-uns] [--mac | --iphone | --ipad | --appletv]

optional arguments:
  -h, --help              Shows this help message and exits.
  -l, --logfile           Saves logging messages to simplemdm2snipe.log instead of displaying on screen.
  -v, --verbose           Sets the logging level to INFO and gives you a better idea of what the script is doing.
  -d, --debug             Sets logging to include additional DEBUG messages.
  --dryrun                This checks your config and tries to contact both the SimpleMDM and Snipe-IT instances, but exits before updating or syncing any assets.
  --version               Shows the version of this script and exits.
  --auto_incrementing     You can use this if you have auto-incrementing enabled in your Snipe-IT instance to utilize that instead of using SIMPLEMDM-<SERIAL NUMBER> for the asset tag.
  --do_not_update_simplemdm  Does not update SimpleMDM with the asset tags stored in Snipe-IT.
  --do_not_verify_ssl     Skips SSL verification for all Snipe-IT requests. Helpful when you use self-signed certificate.
  -r, --ratelimited       Puts a half second delay between Snipe-IT API calls to adhere to the standard 120/minute rate limit
  -f, --force             Updates the Snipe-IT asset with information from SimpleMDM every time, despite what the timestamps indicate.
  -u, --users             Checks in/out assets based on the user assignment in SimpleMDM.
  -uns, --users_no_search Doesn't search for any users if the specified fields in SimpleMDM and Snipe-IT don't match. (case insensitive)
  --mac                   Runs against SimpleMDM Mac computers only.
  --iphone                Runs against SimpleMDM iPhones only.
  --ipad                  Runs against SimpleMDM iPads only.
  --appletv               Runs against SimpleMDM Apple TVs only.

```

## Reporting

`simplemdm2snipe_report.py` runs after a sync and posts a summary to Slack:

- **New assets** and **new models** created in Snipe-IT since the run started (read from the Snipe-IT API, so it's accurate regardless of logging flags)
- **Problems**: every WARNING / ERROR line the sync wrote to `simplemdm2snipe.log` during this run, de-duplicated with counts
- **Deferred devices**: devices skipped this run because their model had to be created first (requires `-v`); they're picked up on the next run
- **Run status**: flags a failed run using the sync's exit code

The easiest way to use it is `run_sync.sh`, which records the start time, runs the sync, and then runs the report even if the sync failed. Point your scheduled job at it instead of at `simplemdm2snipe.py`:

```bash
# Uses SYNC_ARGS (default: -l -v -r -u) when no arguments are given
/opt/simplemdm2snipe/run_sync.sh

# Or pass your own sync flags
/opt/simplemdm2snipe/run_sync.sh -l -v -r -u --mac
```

Configure the Slack webhook in the `[reporting]` section of `settings.conf` (see `settings.conf.example`) or with `SLACK_WEBHOOK_URL`. Without a webhook, the report prints to stdout.

The report needs the Snipe-IT API key to have **View** on Assets and Models, which the sync already requires.

Standalone usage:

```
usage: simplemdm2snipe_report [-h] [--since SINCE | --since-hours SINCE_HOURS] [--exit-code EXIT_CODE] [--log LOG]
                              [--config CONFIG] [--print] [--json] [--quiet-if-clean] [--do_not_verify_ssl] [-d] [--version]

  --since           Run start as ISO-8601 (e.g. 2026-10-05T06:00:00Z)
  --since-hours     Report on the last N hours instead (default 24)
  --exit-code       The sync's exit code, so a failed run is flagged
  --log             Path to simplemdm2snipe.log (overrides [reporting] log_file)
  --print           Print the report instead of posting to Slack
  --json            Print the raw report data as JSON
  --quiet-if-clean  Don't post when nothing was added and nothing went wrong
```

## Testing

It is recommended that you use a test/dev Snipe-IT instance for testing and that your backups are up to date. You can spin up a Snipe-IT instance in Docker pretty quickly ([see the Snipe-IT docs](https://snipe-it.readme.io/docs/docker)).

If you do not have a test/dev SimpleMDM tenant, you can test simplemdm2snipe using the `--do_not_update_simplemdm` argument to prevent data being written back to SimpleMDM.

## Acknowledgements

**simplemdm2snipe** is inspired by and forked from [kandji2snipe](https://github.com/grokability/kandji2snipe), which was in turn inspired and forked from [jamf2snipe](https://github.com/grokability/jamf2snipe), created by [Brian Monroe](https://github.com/ParadoxGuitarist). Thank you for your contributions to the Mac Admin and Open Source communities!

## Contributing

If you have something you'd like to add please help by forking this project then creating a pull request to the `develop` branch. When working on new features, please try to keep existing configs running in the same manner with no changes. When possible, open up an issue and reference it when you make your pull request.
