#!/usr/bin/env python3
# simplemdm2snipe
#
# ABOUT:
#   This python3 script leverages the SimpleMDM and Snipe-IT APIs to sync device details
#   from SimpleMDM to Snipe-IT and sync asset tags from Snipe-IT to SimpleMDM.
#
#   https://simplemdm.com
#   https://snipeitapp.com
#
# LICENSE:
#   MIT
#
# CONFIGURATION:
#   simplemdm2snipe settings are set in the settings.conf file. For more detais please see
#   the README at https://github.com/kelleycomputing/simplemdm2snipe
#

version = "1.0.0"

# Standard Library Imports
import json
import time
import configparser
import argparse
import logging
import sys
import html
from datetime import datetime
import os
import base64

# 3rd Party Imports
try:
    import pytz
except ImportError as import_error:
    print(import_error)
    sys.exit(
        "Looks like you need to install the pytz module. Open a Terminal and run  "
        "\033[1m python3 -m pip install pytz\033[0m."
    )

try:
    import requests
except ImportError as import_error:
    print(import_error)
    sys.exit(
        "Looks like you need to install the requests module. Open a Terminal and run "
        "\033[1m python3 -m pip install requests\033[0m."
    )

from requests.adapters import HTTPAdapter

# Define runtime arguments
runtimeargs = argparse.ArgumentParser()
runtimeargs.add_argument("-l", "--logfile", help="Saves logging messages to simplemdm2snipe.log instead of displaying on screen.", action="store_true")
runtimeargs.add_argument("-v", "--verbose", help="Sets the logging level to INFO and gives you a better idea of what the script is doing.", action="store_true")
runtimeargs.add_argument("-d", "--debug", help="Sets logging to include additional DEBUG messages.", action="store_true")
runtimeargs.add_argument("--dryrun", help="This checks your config and tries to contact both the SimpleMDM and Snipe-IT instances, but exits before updating or syncing any assets.", action="store_true")
runtimeargs.add_argument("--version", help="Prints the version of this script and exits.", action="store_true")
runtimeargs.add_argument("--auto_incrementing", help="You can use this if you have auto-incrementing enabled in your Snipe-IT instance to utilize that instead of using SIMPLEMDM-<SERIAL NUMBER> for the asset tag.", action="store_true")
runtimeargs.add_argument("--do_not_update_simplemdm", help="Does not update SimpleMDM with the asset tags stored in Snipe-IT.", action="store_false")
runtimeargs.add_argument("--do_not_verify_ssl", help="Skips SSL verification for all Snipe-IT requests. Helpful when you use self-signed certificate.", action="store_false")
runtimeargs.add_argument("-r", "--ratelimited", help="Puts a half second delay between Snipe-IT API calls to adhere to the standard 120/minute rate limit", action="store_true")
runtimeargs.add_argument("-f", "--force", help="Updates the Snipe-IT asset with information from SimpleMDM every time, despite what the timestamps indicate.", action="store_true")
runtimeargs.add_argument("-u", "--users", help="Checks in/out assets based on the user assignment in SimpleMDM.", action="store_true")
runtimeargs.add_argument("-uns", "--users_no_search", help="Doesn't search for any users if the specified fields in SimpleMDM and Snipe-IT don't match. (case insensitive)", action="store_true")
type_opts = runtimeargs.add_mutually_exclusive_group()
type_opts.add_argument("--mac", help="Runs against SimpleMDM Mac computers only.", action="store_true")
type_opts.add_argument("--iphone", help="Runs against SimpleMDM iPhones only.", action="store_true")
type_opts.add_argument("--ipad", help="Runs against SimpleMDM iPads only.", action="store_true")
type_opts.add_argument("--appletv", help="Runs against SimpleMDM Apple TVs only.", action="store_true")
user_args = runtimeargs.parse_args()

validarrays = [
        "attributes",
        "id",
        "general",
        "mdm",
        "activation_lock",
        "filevault",
        "automated_device_enrollment",
        "simplemdm_agent",
        "hardware_overview",
        "volumes",
        "network",
        "recovery_information",
        "users",
        "installed_profiles",
        "apple_business_manager",
        "security_information"
]

# Define Functions 

# Find and validate the settings.conf file  
def get_settings():
    # Find a valid settings.conf file.
    logging.info("Searching for a valid settings.conf file.")
    global config
    config = configparser.ConfigParser()
    logging.debug("Checking for a settings.conf in /opt/simplemdm2snipe ...")
    config.read("/opt/simplemdm2snipe/settings.conf")
    if 'snipe-it' not in set(config):
        logging.debug("No valid config found in: /opt Checking for a settings.conf in /etc/simplemdm2snipe ...")
        config.read('/etc/simplemdm2snipe/settings.conf')
    if 'snipe-it' not in set(config):
        logging.debug("No valid config found in /etc Checking for a settings.conf in current directory ...")
        config.read("settings.conf")
    if 'snipe-it' not in set(config):
        logging.debug("No valid config found in current folder.")
        logging.error("No valid settings.conf was found. Refer to the README for valid locations.")
        sys.exit(exit_error_message)

    logging.info("Settings.conf found.")

    # Settings.conf Value Validation - Ensuring some important settings are not empty or default values
    logging.debug("Checking the settings.conf file for valid values.")

    if os.environ.get("SIMPLEMDM_APITOKEN") == "":
        if config['simplemdm']['apitoken'] == "simplemdm-api-bearer-token-here" or config['simplemdm']['apitoken'] == "" :
            logging.error('Invalid SimpleMDM API Token, check your settings.conf or environment variables and try again.')
            sys.exit(exit_error_message)

    if config['snipe-it']['url'] == "https://your_snipe_instance.com" or config['snipe-it']['url'] == "":
        logging.error('Invalid Snipe-IT URL, check your settings.conf and try again.')
        sys.exit(exit_error_message)

    if os.environ.get("SNIPE_APIKEY") == "":
        if config['snipe-it']['apikey'] == "snipe-api-key-here" or config['snipe-it']['apikey'] == "" :
            logging.error('Invalid Snipe-IT API Key, check your settings.conf or environment variables and try again.')
            sys.exit(exit_error_message)

    if config['snipe-it']['mac_custom_fieldset_id'] != "":
        for key in config['mac-api-mapping']:
            simplemdmsplit = config['mac-api-mapping'][key].split()
            if simplemdmsplit[0] in validarrays:
                logging.debug('Found valid array: {}'.format(simplemdmsplit[0]))
                continue
            else:
                logging.error("Found invalid array: {} in the settings.conf file.\nThis is not in the acceptable list of arrays. Check your settings.conf\n Valid arrays are: {}".format(simplemdmsplit[0], ', '.join(validarrays)))
                sys.exit(exit_error_message)
    if config['snipe-it']['iphone_custom_fieldset_id'] != "":
        for key in config['iphone-api-mapping']:
            simplemdmsplit = config['iphone-api-mapping'][key].split()
            if simplemdmsplit[0] in validarrays:
                logging.debug('Found valid array: {}'.format(simplemdmsplit[0]))
                continue
            else:
                logging.error("Found invalid array: {} in the settings.conf file.\nThis is not in the acceptable list of arrays. Check your settings.conf\n Valid arrays are: {}".format(simplemdmsplit[0], ', '.join(validarrays)))
                sys.exit(exit_error_message)
    if config['snipe-it']['ipad_custom_fieldset_id'] != "":
        for key in config['ipad-api-mapping']:
            simplemdmsplit = config['ipad-api-mapping'][key].split()
            if simplemdmsplit[0] in validarrays:
                logging.debug('Found valid array: {}'.format(simplemdmsplit[0]))
                continue
            else:
                logging.error("Found invalid array: {} in the settings.conf file.\nThis is not in the acceptable list of arrays. Check your settings.conf\n Valid arrays are: {}".format(simplemdmsplit[0], ', '.join(validarrays)))
                sys.exit(exit_error_message)
    if config['snipe-it']['appletv_custom_fieldset_id'] != "":
        for key in config['appletv-api-mapping']:
            simplemdmsplit = config['appletv-api-mapping'][key].split()
            if simplemdmsplit[0] in validarrays:
                logging.debug('Found valid array: {}'.format(simplemdmsplit[0]))
                continue
            else:
                logging.error("Found invalid array: {} in the settings.conf file.\nThis is not in the acceptable list of arrays. Check your settings.conf\n Valid arrays are: {}".format(simplemdmsplit[0], ', '.join(validarrays)))
                sys.exit(exit_error_message)

# Create variables based on setings.conf values
def create_variables():
    # Create Global Variables
    global simplemdm_base
    global simplemdm_apitoken
    global simplemdmheaders
    global snipe_base
    global snipe_apikey
    global snipeheaders
    global defaultStatus
    global apple_manufacturer_id
    global simplemdm_apitoken_encoded
    global simplemdm_asset_tag_attribute
    global simplemdm_username_attribute
    
    logging.info('Creating variables from settings.conf')

    # SimpleMDM Base URL
    simplemdm_base = f"https://a.simplemdm.com"
    logging.info("The SimpleMDM base url is: {}".format(simplemdm_base))

    # SimpleMDM API Token
    simplemdm_apitoken = os.environ.get("SIMPLEMDM_APITOKEN", config['simplemdm']['apitoken'])
    logging.debug("The SimpleMDM API token is: {}".format(simplemdm_apitoken))
    
    # SimpleMDM API Token encoded
    # Uses Basic authentication with an empty username, which is essentially:
    # username:password encoded as base64
    simplemdm_apitoken_auth_string = '{}:'.format(simplemdm_apitoken)
    simplemdm_apitoken_encoded = base64.b64encode(simplemdm_apitoken_auth_string.encode('ascii')).decode('ascii')
    logging.debug("The encoded SimpleMDM API token is: {}".format(simplemdm_apitoken_encoded))

    # SimpleMDM asset tag custom attribute name
    simplemdm_asset_tag_attribute = config['simplemdm']['asset_tag_attribute']
    logging.debug("The SimpleMDM asset tag custom attribute name is: {}".format(simplemdm_asset_tag_attribute))

    # SimpleMDM user name custom attribute name
    simplemdm_username_attribute = config['simplemdm']['username_attribute']
    logging.debug("The SimpleMDM user name custom attribute name is: {}".format(simplemdm_username_attribute))

    # Snipe-IT base URL, API key, default status, and Apple manufacturer ID
    snipe_base = config['snipe-it']['url']
    logging.info("The Snipe-IT base url is: {}".format(snipe_base))
    
    # Snipe API Key
    snipe_apikey = os.environ.get("SNIPE_APIKEY",config['snipe-it']['apikey'])
    logging.debug("The Snipe-IT API key is: {}".format(snipe_apikey))
    
    defaultStatus = config['snipe-it']['defaultStatus']
    logging.info("Status ID for new assets created in Snipe-IT: {}".format(defaultStatus))
    apple_manufacturer_id = config['snipe-it']['manufacturer_id']
    logging.info("The Snipe-IT manufacturer ID for Apple is: {}".format(apple_manufacturer_id))

    # Headers for the API calls
    logging.info("Creating the headers we'll need for API calls")
    simplemdmheaders = {'Authorization': 'Basic {}'.format(simplemdm_apitoken_encoded),'Accept': 'application/json','Content-Type':'application/json;charset=utf-8','Cache-Control': 'no-cache'}
    snipeheaders = {'Authorization': 'Bearer {}'.format(snipe_apikey),'Accept': 'application/json','Content-Type':'application/json'}
    logging.debug('Request headers for SimpleMDM will be: {}\nRequest headers for Snipe-IT will be: {}'.format(simplemdmheaders, snipeheaders))

# Configure logging and set logging level
def set_logging():
    global exit_error_message
    # Configure logging
    if user_args.logfile:
        log_file = 'simplemdm2snipe.log'
        exit_error_message = 'simplemdm2snipe exited due to an error. Please check simplemdm2snipe.log for details.'
    else:
        log_file = ''
        exit_error_message = 1


    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'

    # Set logging level
    if user_args.verbose:
        logging.basicConfig(level=logging.INFO,format=log_format,datefmt=date_format,filename=log_file)
        logging.info('Verbose Logging Enabled...')
    elif user_args.debug:
        logging.basicConfig(level=logging.DEBUG,format=log_format,datefmt=date_format,filename=log_file)
        logging.info('Debug Logging Enabled...')
    else:
        logging.basicConfig(level=logging.WARNING,format=log_format,datefmt=date_format,filename=log_file)

# Verify that Snipe-IT is accessible
def snipe_access_test():
    try:
        SNIPE_UP = True if requests.get(snipe_base, verify=user_args.do_not_verify_ssl).status_code == 200 else False
    except Exception as e:
        logging.exception(e)
        SNIPE_UP = False
    if not SNIPE_UP:
        logging.error('Snipe-IT cannot be reached from here. \nPlease check the Snipe-IT url in the settings.conf file.')
        sys.exit(exit_error_message)
    else:
        logging.info('We were able to get a good response from your Snipe-IT instance.')

# Verify that SimpleMDM is accessible
def simplemdm_access_test():
    try:
        api_url = '{0}/api/v1/devices'.format(simplemdm_base)
        SIMPLEMDM_UP = True if requests.get(api_url).status_code in (200, 401) else False
    except Exception as e:
        logging.exception(e)
        SIMPLEMDM_UP = False
    if not SIMPLEMDM_UP:
        logging.error('SimpleMDM cannot be reached from here. \nPlease check the SimpleMDM tenant and region in the settings.conf file.')
        sys.exit(exit_error_message)
    else:
        logging.info('We were able to get a good response from your SimpleMDM instance.')

# Initialize rate limiting counters
snipe_api_count = 0
first_snipe_call = None

# This function is run every time a request is made, handles rate limiting for Snipe-IT.
def request_handler(r, *args, **kwargs):
    global snipe_api_count
    global first_snipe_call

    if snipe_base not in r.url:
        return r

    # Handle 429 rate limit responses with retry and exponential backoff
    if r.status_code == 429 or '"messages":429' in r.text:
        re_req = r.request
        for attempt in range(5):
            backoff_time = 2 ** attempt  # 1, 2, 4, 8, 16 seconds
            logging.warning("Rate limited by Snipe-IT. Backing off for {} seconds (attempt {}/5)...".format(backoff_time, attempt + 1))
            time.sleep(backoff_time)
            s = requests.Session()
            s.headers.update(snipeheaders)
            retry_response = s.send(re_req, verify=user_args.do_not_verify_ssl)
            if retry_response.status_code != 429 and '"messages":429' not in retry_response.text:
                logging.info("Retry succeeded after backoff.")
                return retry_response
        logging.error("Still rate limited after 5 retries. Exiting.")
        sys.exit(exit_error_message)

    # Proactive rate limiting when -r flag is used
    if user_args.ratelimited:
        if first_snipe_call is None:
            first_snipe_call = time.time()
            time.sleep(0.5)
        snipe_api_count += 1
        time_elapsed = time.time() - first_snipe_call
        if time_elapsed > 0:
            snipe_api_rate = snipe_api_count / time_elapsed
            if snipe_api_rate > 1.95:
                sleep_time = 0.5 + (snipe_api_rate - 1.95)
                logging.debug('Going over Snipe-IT rate limit of 120/minute ({:.2f}/sec), sleeping for {:.2f}s'.format(snipe_api_rate, sleep_time))
                time.sleep(sleep_time)
            logging.debug("Made {} requests to Snipe-IT in {:.1f} seconds ({:.2f} req/sec)".format(snipe_api_count, time_elapsed, snipe_api_rate))

    return r

# SimpleMDM API Error Handling
def simplemdm_error_handling(resp, resp_code, err_msg):
    """Handle HTTP errors."""
    # 400
    if resp_code == requests.codes["bad_request"]:
        logging.error(f"{err_msg}")
        logging.error(f"\tResponse msg: {resp.text}\n")
        sys.exit(exit_error_message)
    # 401
    elif resp_code == requests.codes["unauthorized"]:
        logging.error(f"{err_msg}")
        logging.error(
            "This error can occur if the token is incorrect, was revoked, the required "
            "permissions are missing, or the token has expired.")
        sys.exit(exit_error_message)
    # 403
    elif resp_code == requests.codes["forbidden"]:
        logging.error(f"{err_msg}")
        logging.error("The api key may be invalid or missing.")
        sys.exit(exit_error_message)
    # 404
    elif resp_code == requests.codes["not_found"]:
        logging.error("\nWe cannot find the one that you are looking for...")
        logging.error(f"\tError: {err_msg}")
        logging.error(f"\tResponse msg: {resp}")
        logging.error(
            "\tPossible reason: If this is a device it could be because the device is "
            "no longer\n"
            "\t\t\t enrolled in SimpleMDM. This would prevent the MDM command from being\n"
            "\t\t\t sent successfully.\n"
        )
        sys.exit(exit_error_message)
    # 422
    elif resp_code == requests.codes["unprocessable_entity"]:
        logging.warning(f"SimpleMDM rejected the request (422 Unprocessable Entity): {err_msg}")
        logging.warning(f"\tResponse msg: {resp.text}")
        logging.warning("\tThis often means a custom attribute (e.g. 'asset_tag') has not been created in SimpleMDM yet.")
        logging.warning("\tSkipping this update and continuing...")
        return
    # 429
    elif resp_code == requests.codes["too_many_requests"]:
        logging.error(f"{err_msg}")
        logging.error("You have reached the rate limit ...")
        print("Try again later ...")
        sys.exit(exit_error_message)
    # 500
    elif resp_code == requests.codes["internal_server_error"]:
        logging.error(f"{err_msg}")
        logging.error("The service is having a problem...")
        sys.exit(exit_error_message)
    # 503
    elif resp_code == requests.codes["service_unavailable"]:
        logging.error(f"{err_msg}")
        logging.error("Unable to reach the service. Try again later...")
        sys.exit(exit_error_message)
    else:
        logging.error("Unexpected error from SimpleMDM (HTTP {}): {}".format(resp_code, err_msg))
        logging.error(f"\tResponse msg: {resp.text}")
        sys.exit(exit_error_message)

# Function to use the SimpleMDM API
def simplemdm_api(method, endpoint, params=None, payload=None):
    """Make an API request and return data.
    method   - an HTTP Method (GET, POST, PATCH, DELETE).
    endpoint - the API URL endpoint to target.
    params   - optional parameters can be passed as a dict.
    payload  - optional payload is passed as a dict and used with PATCH and POST
               methods.
    Returns a JSON data object.
    """
    attom_adapter = HTTPAdapter(max_retries=3)
    session = requests.Session()
    session.mount(simplemdm_base, attom_adapter)

    try:
        response = session.request(
            method,
            simplemdm_base + endpoint,
            data=payload,
            headers=simplemdmheaders,
            params=params,
            timeout=30,
        )

        # If a successful status code is returned (200 and 300 range)
        if response:
            try:
                data = response.json()
            except Exception:
                data = response.text

        # If the request is successful exceptions will not be raised
        response.raise_for_status()

    except requests.exceptions.RequestException as err:
        simplemdm_error_handling(resp=response, resp_code=response.status_code, err_msg=err)
        data = {"error": f"{response.status_code}", "api resp": f"{err}"}

    return data

# Function to get device records from SimpleMDM
def get_simplemdm_devices():
    count = 0
    # dict placeholder for params passed to api requests
    params = {}
    # limit - set the number of records to return per API call
    limit = 300
    # starting_after - set the starting point within a list of resources
    starting_after = 0
    # inventory
    data = []
    
    # has_more - set when pagination indicates that more than limit devices were returned
    has_more = True

    while has_more:
        # update params
        params.update(
            {"limit": f"{limit}", "starting_after": f"{starting_after}"}
        )

        # get devices
        endpoint="/api/v1/devices"
        logging.debug('Calling for all devices in SimpleMDM against: {}'.format(simplemdm_base + endpoint))
        response = simplemdm_api(method="GET", endpoint=endpoint, params=params)
        count += len(response['data'])
        if response['data']:
            starting_after = response['data'][-1]['id']
        has_more = response['has_more']

        logging.debug('Retrieved {} SimpleMDM devices and has_more is:{}'.format(count, has_more))

        # breakout the response then append to the data list
        for record in response['data']:
            data.append(record)

    return data

# Function to lookup details of a specific SimpleMDM asset using the Device ID.
def get_simplemdm_device_details(simplemdm_id):
    endpoint=f"/api/v1/devices/{simplemdm_id}"
    logging.debug('Calling for device details in SimpleMDM against: {}'.format(simplemdm_base + endpoint))
    response = simplemdm_api(method="GET", endpoint=endpoint)
    return response['data']

# Function to lookup last activity date and time for a SimpleMDM asset.
def get_simplemdm_device_activity_date(simplemdm_id):
    endpoint=f"/api/v1/devices/{simplemdm_id}"
    logging.debug('Calling for device activity in SimpleMDM against: {}'.format(simplemdm_base + endpoint))
    response = simplemdm_api(method="GET", endpoint=endpoint)
    return response['data']['attributes']['last_seen_at']

# Function to lookup custom_attributes for a SimpleMDM asset
def get_simplemdm_device_custom_attributes(simplemdm_id):
    endpoint=f"/api/v1/devices/{simplemdm_id}/custom_attribute_values"
    logging.debug('Calling for device activity in SimpleMDM against: {}'.format(simplemdm_base + endpoint))
    response = simplemdm_api(method="GET", endpoint=endpoint)
    return response['data']

# Function to get device type from product name
def get_simplemdm_device_type(product_name):
    if 'iPhone' in product_name:
        return 'iphone'
    elif 'iPad' in product_name:
        return 'ipad'
    elif 'AppleTV' in product_name:
        return 'appletv'
    else:
        return 'mac'

# Function to get SimpleMDM custom attribute value
def get_simplemdm_custom_attribute(device_id, attribute):
    value = None
    for custom_attribute in simplemdm_device['relationships']['custom_attribute_values']['data']:
        if custom_attribute['id'] == attribute:
            value = custom_attribute['attributes']['value']
    return value

# Function to update the asset tag of devices in SimpleMDM with an number passed from Snipe-IT.
def update_simplemdm_asset_tag(simplemdm_id, asset_tag):
    endpoint=f"/api/v1/devices/{simplemdm_id}/custom_attribute_values"
    payload_dict = {"data": [{"name": simplemdm_asset_tag_attribute, "value": asset_tag}]}
    payload = json.dumps(payload_dict)
    logging.debug('Making PUT request against: {}\n\tPayload for the request is: {}'.format(simplemdm_base + endpoint, payload))
    response = simplemdm_api(method="PUT", endpoint=endpoint,payload=payload)
    return response

# Function to lookup a Snipe-IT asset by serial number.
def search_snipe_asset(serial):
    api_url = '{}/api/v1/hardware/byserial/{}'.format(snipe_base, serial)
    response = requests.get(api_url, headers=snipeheaders, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
    if response.status_code == 200:
        jsonresponse = response.json()
        # Check to make sure there's actually a result
        if "total" in jsonresponse:
            if jsonresponse['total'] == 1:
                return jsonresponse
            elif jsonresponse['total'] == 0:
                logging.info("No assets match {}".format(serial))
                return "NoMatch"
            else:
                logging.warning('FOUND {} matching assets while searching for: {}'.format(jsonresponse['total'], serial))
                return "MultiMatch"
        else:
            logging.info("No assets match {}".format(serial))
            return "NoMatch"
    else:
        logging.warning('Snipe-IT responded with error code:{} when we tried to look up: {}'.format(response.text, serial))
        logging.debug('{} - {}'.format(response.status_code, response.content))
        return "ERROR"

# Function to get all the asset models from Snipe-IT
def get_snipe_models():
    api_url = '{}/api/v1/models'.format(snipe_base)
    logging.debug('Calling against: {}'.format(api_url))
    response = requests.get(api_url, headers=snipeheaders, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
    if response.status_code == 200:
        jsonresponse = response.json()
        logging.info("Got a valid response that should have {} models.".format(jsonresponse['total']))
        if jsonresponse['total'] <= len(jsonresponse['rows']) :
            return jsonresponse
        else:
            logging.info("We didn't get enough results so we need to get them again.")
            api_url = '{}/api/v1/models?limit={}'.format(snipe_base, jsonresponse['total'])
            newresponse = requests.get(api_url, headers=snipeheaders, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
            if response.status_code == 200:
                newjsonresponse = newresponse.json()
                if newjsonresponse['total'] == len(newjsonresponse['rows']) :
                    return newjsonresponse
                else:
                    logging.error("Unable to get all models from Snipe-IT")
                    sys.exit(exit_error_message)
            else:
                logging.error('When we tried to retreive a list of models, Snipe-IT responded with error status code:{} - {}'.format(response.status_code, response.content))
                sys.exit(exit_error_message)
    else:
        logging.error('When we tried to retreive a list of models, Snipe-IT responded with error status code:{} - {}'.format(response.status_code, response.content))
        sys.exit(exit_error_message)

# Recursive function returns all users in a Snipe-IT Instance, 100 at a time.
def get_snipe_users(previous=[]):
    user_id_url = '{}/api/v1/users'.format(snipe_base)
    payload = {
        'limit': 100,
        'offset': len(previous)
    }
    logging.debug('The payload for the Snipe-IT users GET is {}'.format(payload))
    response = requests.get(user_id_url, headers=snipeheaders, params=payload, hooks={'response': request_handler})
    response_json = response.json()
    current = response_json['rows']
    if len(previous) != 0:
        current = previous + current
    if response_json['total'] > len(current):
        logging.debug('We have more than 100 users, get the next page - total: {} current: {}'.format(response_json['total'], len(current)))
        return get_snipe_users(current)
    else:
        return current

# Function to search Snipe-IT for a user
def get_snipe_user_id(username):
    if username == '':
        return "NotFound"
    username = username.lower()
    for user in snipe_users:
        for value in user.values():
            if str(value).lower() == username:
                id = user['id']
                return id
    if user_args.users_no_search:
        logging.debug("No matches in snipe_users for {}, not querying the API for the next closest match since we've been told not to".format(username))
        return "NotFound"
    logging.debug('No matches in snipe_users for {}, querying the API for the next closest match'.format(username))
    user_id_url = '{}/api/v1/users'.format(snipe_base)
    payload = {
        'search':username,
        'limit':1,
        'sort':'username',
        'order':'asc'
    }
    logging.debug('The payload for the Snipe-IT user search is: {}'.format(payload))
    response = requests.get(user_id_url, headers=snipeheaders, params=payload, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
    try:
        return response.json()['rows'][0]['id']
    except:
        return "NotFound"

# Function that creates a new Snipe-IT model - not an asset - with a JSON payload
def create_snipe_model(payload):
    api_url = '{}/api/v1/models'.format(snipe_base)
    logging.debug('Calling to create new snipe model type against: {}\nThe payload for the POST request is:{}\nThe request headers can be found near the start of the output.'.format(api_url, payload))
    response = requests.post(api_url, headers=snipeheaders, json=payload, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
    if response.status_code == 200:
        jsonresponse = response.json()
        if jsonresponse.get('payload') is None:
            logging.warning('Model creation failed for {}: {}'.format(payload.get('name'), jsonresponse.get('messages')))
            return False
        modelnumbers[jsonresponse['payload']['model_number']] = jsonresponse['payload']['id']
        return True
    else:
        logging.warning('Error code: {} while trying to create a new model.'.format(response.status_code))
        return False

# Function to create a new asset by passing array
def create_snipe_asset(payload):
    api_url = '{}/api/v1/hardware'.format(snipe_base)
    logging.debug('Calling to create a new asset against: {}\nThe payload for the POST request is:{}\nThe request headers can be found near the start of the output.'.format(api_url, payload))
    response = requests.post(api_url, headers=snipeheaders, json=payload, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
    logging.debug(response.text)
    if response.status_code == 200:
        logging.debug("Got back status code: 200 - {}".format(response.content))
        jsonresponse = response.json()
        if jsonresponse['status'] == "error":
            logging.error('Asset creation failed for asset {} with error {}'.format(payload['name'],jsonresponse['messages']))
            return 'ERROR', response
        return 'AssetCreated', response
    else:
        logging.error('Asset creation failed for asset {} with error {}'.format(payload['name'],response.text))
        return 'ERROR', response

# Function that updates a Snipe-IT asset with a JSON payload
def update_snipe_asset(snipe_id, payload):
    api_url = '{}/api/v1/hardware/{}'.format(snipe_base, snipe_id)
    logging.debug('The payload for the Snipe-IT update is: {}'.format(payload))
    response = requests.patch(api_url, headers=snipeheaders, json=payload, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
    # Verify that the payload updated properly.
    goodupdate = True
    if response.status_code == 200:
        logging.debug("Got back status code: 200 - Checking the payload updated properly: If you error here it's because you configure the API mapping right.")
        jsonresponse = response.json()
        # Check if there's an Error and Log it, or parse the payload.
        if jsonresponse['status'] == "error":
            logging.error('Unable to update ID: {}. Error "{}"'.format(snipe_id, jsonresponse['messages']))
            goodupdate = False
        else:
            for key in payload:
                if payload[key] == '':
                    payload[key] = None
                if jsonresponse['payload'][key] != payload[key]:
                    logging.warning('Unable to update ID: {}. We failed to update the {} field with "{}"'.format(snipe_id, key, payload[key]))
                    goodupdate = False
                else:
                    logging.info("Sucessfully updated {} with: {}".format(key, payload[key]))
        return goodupdate
    else:
        logging.error('Whoops. Got an error status code while updating ID {}: {} - {}'.format(snipe_id, response.status_code, response.content))
        return False

# Function that checks in an asset in Snipe-IT
def checkin_snipe_asset(asset_id):
    api_url = '{}/api/v1/hardware/{}/checkin'.format(snipe_base, asset_id)
    payload = {
        'note':'Checked in by simplemdm2snipe'
    }
    logging.debug('The payload for the Snipe-IT checkin is: {}'.format(payload))
    response = requests.post(api_url, headers=snipeheaders, json=payload, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
    logging.debug('The response from Snipe-IT is: {}'.format(response.json()))
    if response.status_code == 200:
        logging.debug("Got back status code: 200 - {}".format(response.content))
        return "CheckedOut"
    else:
        return response

# Function that checks out an asset in Snipe-IT
def checkout_snipe_asset(user, asset_id, asset_name, checked_out_user=None):
    logging.debug('Checking out {} (ID: {}) to {}'.format(asset_name,asset_id,user))
    user_id = get_snipe_user_id(user)
    if user_id == 'NotFound':
        logging.info("User {} not found in Snipe-IT, skipping check out".format(user))
        return "NotFound"
    if checked_out_user == None:
        logging.info("Not checked out, checking out {} (ID: {}) to {}.".format(asset_name,asset_id,user))
    elif checked_out_user == "NewAsset":
        logging.info("First time this asset will be checked out, checking out to {}".format(user))
    else:
        logging.info("Checking in {} (ID: {}) to check it out to {}".format(asset_name,asset_id,user))
        checkin_snipe_asset(asset_id)
    api_url = '{}/api/v1/hardware/{}/checkout'.format(snipe_base, asset_id)
    logging.info("Checking out {} (ID: {}) to {}.".format(asset_name,asset_id,user))
    payload = {
        'checkout_to_type':'user',
        'assigned_user':user_id,
        'note':'Checked out by simplemdm2snipe.'
    }
    logging.debug('The payload for the Snipe-IT checkin is: {}'.format(payload))
    response = requests.post(api_url, headers=snipeheaders, json=payload, verify=user_args.do_not_verify_ssl, hooks={'response': request_handler})
    logging.debug('The response from Snipe-IT is: {}'.format(response.json()))
    if response.status_code == 200:
        logging.debug("Got back status code: 200 - {}".format(response.content))
        return "CheckedOut"
    else:
        logging.error('Asset checkout failed for asset {} with error {}'.format(asset_id,response.text))
        return response

### Main Logic ###

# Print version and exit
if user_args.version:
    print('simplemdm2snipe v'+version)
    sys.exit()

# Configure logging and set logging level
set_logging()

# Notify if we're doing a dry run.
if user_args.dryrun and user_args.logfile:
    logging.info('Dry Run: Starting')
    print("Dry Run: Starting")
elif user_args.dryrun:
    logging.info('Dry Run: Starting')

# Validate User Sync Options
if user_args.users_no_search and not user_args.users:
    logging.error("The -uns option requires the use of -u for user syncing.")
    sys.exit(exit_error_message)

# Find and validate the settings.conf file  
get_settings()

# Create variables based on setings.conf values
create_variables()

# Report if we're verifying SSL or not for Snipe-IT
logging.info("SSL Verification for Snipe-IT is set to: {}".format(user_args.do_not_verify_ssl))

# Do some tests to see if the hosts are accessible
logging.info("Running tests to see if hosts are up.")

# Verify that Snipe-IT is accessible
snipe_access_test()

# Verify that SimpleMDM is accessible
simplemdm_access_test()

logging.info("Setup and testing complete. Let's get started...")

### Get Started ###

# Get a list of known models from Snipe-IT
logging.info("Getting a list of models from Snipe-IT.")
snipemodels = get_snipe_models()
logging.debug("Parsing the {} model results for models with model numbers.".format(len(snipemodels['rows'])))
modelnumbers = {}
for model in snipemodels['rows']:
    if model['model_number'] == "":
        logging.debug("The model, {}, did not have a model number. Skipping.".format(model['name']))
        continue
    modelnumbers[model['model_number']] = model['id']
logging.info("Our list of models has {} entries.".format(len(modelnumbers)))
logging.debug("Here's the list of the {} models and their id's that we were able to collect:\n{}".format(len(modelnumbers), modelnumbers))

# Get a list of users from Snipe-IT if the user argument was used
if user_args.users:
    snipe_users = get_snipe_users()

# Get the device_ids of all active assets.
simplemdm_devices = get_simplemdm_devices()

TotalNumber = len(simplemdm_devices)

# Make sure we have a good list.
if TotalNumber != None:
    logging.info('Received a list of SimpleMDM assets that had {} entries.'.format(TotalNumber))
else:
    logging.error("We were not able to retreive a list of assets from your SimpleMDM instance. It's likely that your settings or credentials are incorrect. Check your settings.conf and verify you can make API calls outside of this system with the credentials found in your settings.conf")
    sys.exit(exit_error_message)

# After this point we start editing data, so quit if this is a dry run
if user_args.dryrun and user_args.logfile:
    logging.info('Dry Run: Complete')
    sys.exit('Dry Run: Complete')
elif user_args.dryrun:
    logging.info('Dry Run: Complete')
    sys.exit()
    
# From this point on, we're editing data.
logging.info('Starting to Update Inventory')
CurrentNumber = 0

for simplemdm_device in simplemdm_devices:
    simplemdm_device_type = get_simplemdm_device_type(simplemdm_device['attributes']['product_name'])
    if user_args.mac:
        if simplemdm_device_type != 'mac':
            continue
    if user_args.iphone:
        if simplemdm_device_type != 'iphone':
            continue
    if user_args.ipad:
        if simplemdm_device_type != 'ipad':
            continue
    if user_args.appletv:
        if simplemdm_device_type != 'appletv':
            continue
    CurrentNumber += 1
    logging.info("Processing entry {} out of {} - Device Name: {} - Device ID: {}".format(CurrentNumber, TotalNumber, simplemdm_device['attributes']['device_name'], simplemdm_device['id']))

    # Check that the model number exists in Snipe-IT, if not create it.
    if simplemdm_device_type == 'mac':
        category_id = 'mac_model_category_id'
        custom_fieldset_id = 'mac_custom_fieldset_id'
    elif simplemdm_device_type == 'iphone':
        category_id = 'iphone_model_category_id'
        custom_fieldset_id = 'iphone_custom_fieldset_id'
    elif simplemdm_device_type == 'ipad':
        category_id = 'ipad_model_category_id'
        custom_fieldset_id = 'ipad_custom_fieldset_id'
    elif simplemdm_device_type == 'appletv':
        category_id = 'appletv_model_category_id'
        custom_fieldset_id = 'appletv_custom_fieldset_id'

    if simplemdm_device['attributes']['product_name'] not in modelnumbers:
        logging.info("Could not find a model ID in Snipe-IT for: {}".format(simplemdm_device['attributes']['model']))
        newmodel = {"category_id":int(config['snipe-it'][category_id]),"manufacturer_id":int(apple_manufacturer_id),"name": simplemdm_device['attributes']['model_name'],"model_number":simplemdm_device['attributes']['product_name']}
        if custom_fieldset_id in config['snipe-it']:
            fieldset_split = config['snipe-it'][custom_fieldset_id]
            newmodel['fieldset_id'] = fieldset_split
        if not create_snipe_model(newmodel):
          logging.warning('Skipping asset creation for {} because model could not be created.'.format(simplemdm_device['attributes']['device_name']))
        continue

    # Pass the SN from SimpleMDM to search for a match in Snipe-IT
    snipe = search_snipe_asset(simplemdm_device['attributes']['serial_number'])

    # Create a new asset if there's no match:
    if snipe == 'NoMatch':
        logging.info("Creating a new asset in Snipe-IT for SimpleMDM ID {} - {}".format(simplemdm_device['id'], simplemdm_device['attributes']['device_name']))
        # This section checks to see if an asset tag exists in SimpleMDM, if not it creates one.
        simplemdm_asset_tag = get_simplemdm_custom_attribute(simplemdm_device, simplemdm_asset_tag_attribute)
        if simplemdm_asset_tag:
            logging.debug("Asset tag found in SimpleMDM, setting it to: {}".format(simplemdm_asset_tag))

        if not simplemdm_asset_tag:
            logging.debug('No asset tag found in SimpleMDM, checking settings.conf for custom asset tag patterns.')
            # Check for custom patterns and use them if enabled, otherwise use the default pattern.
            if config['asset-tag']['use_custom_pattern'] == 'yes':
                logging.debug('Custom asset tag patterns found.')
                if simplemdm_device_type == 'mac':
                    tag_split = config['asset-tag']['pattern_mac'].split()
                    simplemdm_asset_tag = tag_split[0]+simplemdm_device['{}'.format(tag_split[1])]['{}'.format(tag_split[2])]
                elif simplemdm_device_type == 'iphone':
                    tag_split = config['asset-tag']['pattern_iphone'].split()
                    simplemdm_asset_tag = tag_split[0]+simplemdm_device['{}'.format(tag_split[1])]['{}'.format(tag_split[2])]
                elif simplemdm_device_type == 'ipad':
                    tag_split = config['asset-tag']['pattern_ipad'].split()
                    simplemdm_asset_tag = tag_split[0]+simplemdm_device['{}'.format(tag_split[1])]['{}'.format(tag_split[2])]
                elif simplemdm_device_type == 'appletv':
                    tag_split = config['asset-tag']['pattern_appletv'].split()
                    simplemdm_asset_tag = tag_split[0]+simplemdm_device['{}'.format(tag_split[1])]['{}'.format(tag_split[2])]
            else:
                logging.debug('No custom asset tag patterns found in settings.conf, using default.')
                simplemdm_asset_tag = 'SIMPLEMDM-{}'.format(simplemdm_device['attributes']['serial_number'])
        # Create the payload
        logging.debug("Payload is being made.")
        newasset = {'asset_tag': simplemdm_asset_tag,'model_id': modelnumbers['{}'.format(simplemdm_device['attributes']['product_name'])], 'name': simplemdm_device['attributes']['device_name'], 'status_id': defaultStatus,'serial': simplemdm_device['attributes']['serial_number']}
        for snipekey in config['{}-api-mapping'.format(simplemdm_device_type)]:
            simplemdmsplit = config['{}-api-mapping'.format(simplemdm_device_type)][snipekey].split()
            try:
                for i, item in enumerate(simplemdmsplit):
                    try:
                        item = int(item)
                    except ValueError:
                        logging.debug('{} is not an integer'.format(item))
                    if i == 0:
                        simplemdm_value = simplemdm_device[item]
                    else:
                        simplemdm_value = simplemdm_value[item]
                newasset[snipekey] = simplemdm_value
            except KeyError:
                continue
        # Reset the payload without the asset_tag if auto_incrementing flag is set.
        if user_args.auto_incrementing:
            newasset.pop('asset_tag', None)
        new_snipe_asset = create_snipe_asset(newasset)
        if new_snipe_asset[0] != "AssetCreated":
            continue
        if user_args.users:
            # This section checks to see if a username is assigned in SimpleMDM.
            simplemdm_username = get_simplemdm_custom_attribute(simplemdm_device, simplemdm_username_attribute)
            if simplemdm_username:
                logging.info("Username found in SimpleMDM, setting it to: {}".format(simplemdm_username))
            else:
                logging.info("No user is assigned to {} in SimpleMDM, not checking it out.".format(simplemdm_device['attributes']['device_name']))
                continue
            logging.info('Checking out new item {} to user {}'.format(simplemdm_device['attributes']['device_name'], simplemdm_username))
            checkout_snipe_asset(simplemdm_username, new_snipe_asset[1].json()['payload']['id'], "NewAsset")

    # Log an error if there's an issue, or more than once match.
    elif snipe == 'MultiMatch':
        logging.warning("WARN: You need to resolve multiple assets with the same serial number in your inventory. If you can't find them in your inventory, you might need to purge your deleted records. You can find that in the Snipe-IT Admin settings. Skipping serial number {} for now.".format(simplemdm_device['attributes']['serial_number']))
    elif snipe == 'ERROR':
        logging.error("We got an error when looking up serial number {} in Snipe-IT, which shouldn't happen at this point. Check your Snipe-IT instance and setup. Skipping for now.".format(simplemdm_device['attributes']['serial_number']))

    else:
        # Only update if SimpleMDM has more recent info.
        snipe_id = snipe['rows'][0]['id']
        snipe_time = snipe['rows'][0]['updated_at']['datetime']
        simplemdm_device_activity = get_simplemdm_device_activity_date(simplemdm_device['id'])
        simplemdm_time_conversion = datetime.strptime(simplemdm_device_activity, '%Y-%m-%dT%H:%M:%S.%f%z')
        simplemdm_time_conversion = simplemdm_time_conversion.astimezone(pytz.timezone(config['snipe-it']['timezone']))
        simplemdm_time = simplemdm_time_conversion.strftime('%Y-%m-%d %H:%M:%S')

        # Check to see that the SimpleMDM record is newer than the previous Snipe-IT update, or if it is a new record in Snipe-IT
        if ( simplemdm_time > snipe_time ) or ( user_args.force ):
            if user_args.force:
                logging.info("Forcing the update regardless of the timestamps due to -f being used.")
            logging.debug("Updating the Snipe-IT asset because SimpleMDM has a more recent timestamp: {} > {} or the Snipe-IT record is new".format(simplemdm_time, snipe_time))
            updates = {}

            if html.unescape(snipe['rows'][0]['name']) != simplemdm_device['attributes']['device_name']:
                logging.info('Device name changed in SimpleMDM... Updating Snipe-IT')
                updates={'name': simplemdm_device['attributes']['device_name']}

            for snipekey in config['{}-api-mapping'.format(simplemdm_device_type)]:
                try:
                    simplemdmsplit = config['{}-api-mapping'.format(simplemdm_device_type)][snipekey].split()
                    for i, item in enumerate(simplemdmsplit):
                        try:
                            item = int(item)
                        except ValueError:
                            logging.debug('{} is not an integer'.format(item))
                        if i == 0:
                            simplemdm_value = simplemdm_device[item]
                        else:
                            simplemdm_value = simplemdm_value[item]
                    payload = {snipekey: simplemdm_value}
                    latestvalue = simplemdm_value
                except KeyError:
                    logging.debug("Skipping the payload, because the SimpleMDM key we're mapping to doesn't exist")
                    continue

                # Need to check that we're not needlessly updating the asset.
                # If it's a custom value it'll fail the first section and send it to except section that will parse custom sections.
                try:
                    if snipe['rows'][0][snipekey] != latestvalue:
                        updates.update(payload)
                    else:
                        logging.debug("Skipping the payload, because it already exits.")
                except:
                    logging.debug("The snipekey lookup failed, which means it's a custom field. Parsing those to see if it needs to be updated or not.")
                    needsupdate = False
                    for CustomField in snipe['rows'][0]['custom_fields']:
                        if snipe['rows'][0]['custom_fields'][CustomField]['field'] == snipekey :
                            if snipe['rows'][0]['custom_fields'][CustomField]['value'] != str(latestvalue):
                                logging.debug("Found the field, and the value needs to be updated from {} to {}".format(snipe['rows'][0]['custom_fields'][CustomField]['value'], latestvalue))
                                needsupdate = True
                    if needsupdate == True:
                        updates.update(payload)
                    else:
                        logging.debug("Skipping the payload, because it already exists, or the Snipe-IT key we're mapping to doesn't.")

            if updates:
                update_snipe_asset(snipe_id, updates)

            if user_args.users:
                simplemdm_username = get_simplemdm_custom_attribute(simplemdm_device, simplemdm_username_attribute)

                if snipe['rows'][0]['status_label']['status_meta'] in ('deployable', 'deployed'):
                    if snipe['rows'][0]['assigned_to'] and not simplemdm_username:
                        logging.info("No user is assigned to {} in SimpleMDM, checking it in.".format(simplemdm_device['attributes']['device_name']))
                        checkin_snipe_asset(snipe_id)
                    elif not simplemdm_username:
                        logging.info("No user is assigned to {} in SimpleMDM, skipping check out.".format(simplemdm_device['attributes']['device_name']))
                        continue
                    elif snipe['rows'][0]['assigned_to'] == None or snipe['rows'][0]['assigned_to']['email'] != simplemdm_username:
                        logging.info('Checking out {} to user {}'.format(simplemdm_device['attributes']['device_name'], simplemdm_username))
                        checkout_snipe_asset(simplemdm_username, snipe_id, simplemdm_device['attributes']['device_name'], snipe['rows'][0]['assigned_to'])
                    elif snipe['rows'][0]['assigned_to']['email'] == simplemdm_username:
                        logging.info("{} is already checked out to {}, skipping check out.".format(simplemdm_device['attributes']['device_name'],snipe['rows'][0]['assigned_to']['email']))
                        continue
                    else:
                        logging.info("Failed checking out {} to {}.".format(simplemdm_device['attributes']['device_name'],snipe['rows'][0]['assigned_to']['email']))
                else:
                    logging.info("Can't checkout {} since the status isn't set to deployable".format(simplemdm_device['attributes']['device_name']))

        else:
            logging.info("Snipe-IT record is newer than the SimpleMDM record. Nothing to sync. If this wrong, then force an inventory update in SimpleMDM")
            logging.debug("Not updating the Snipe-IT asset because Snipe-IT has a more recent timestamp: {} < {}".format(simplemdm_time, snipe_time))

        # Sync the Snipe-IT Asset Tag Number back to SimpleMDM if needed
        # The user arg below is set to false if it's called, so this would fail if the user called it.
        simplemdm_asset_tag = get_simplemdm_custom_attribute(simplemdm_device, simplemdm_asset_tag_attribute)
        if (simplemdm_asset_tag != snipe['rows'][0]['asset_tag']) and user_args.do_not_update_simplemdm :
            logging.info("Asset tag changed in Snipe-IT... Updating SimpleMDM")
            if snipe['rows'][0]['asset_tag'][0]:
                update_simplemdm_asset_tag("{}".format(simplemdm_device['id']), '{}'.format(snipe['rows'][0]['asset_tag']))
                logging.info("Updating device record")

if user_args.ratelimited:
    logging.debug('Total amount of API calls made: {}'.format(snipe_api_count))
