import veracross_api
import lightspeed_api
import sys
import getopt
import os
import datetime
import pandas
from decimal import Decimal, ROUND_HALF_UP
import logging
import json


def load_json(file):
    f = open(file)
    r = json.load(f)
    return r


def get_ls_customer_types(lightspeed_connection):
    ls_customer_types = dict()

    try:
        ct = lightspeed_connection.get("CustomerType")
        for i in ct['CustomerType']:
            ls_customer_types[i["name"]] = i["customerTypeID"]
    except:
        print("Cannot get customer types from Lightspeed API, or none exist.")
        sys.exit(2)

    return ls_customer_types


def sync_ls_vc(config, options):
    c = config
    ls = lightspeed_api.Lightspeed(c)
    vc = veracross_api.Veracross(c)

    # Make sure we have a lastsync and veracross id field mapped.
    if c["import_options_veracrossid"] is None or c["import_options_lastsync"] is None:
        print("Missing import_options_veracrossid or import_options_lastsync in config file.")
        sys.exit(2)

    # Placeholder for parameters
    param = {}

    # Determine if we are syncing VC changes after particular date and update params set to VC.
    if "after_date" in options["sync_filters"]:
        if options["sync_filters"]["after_date"]:
            param.update({"updated_after": str(options["sync_filters"]["after_date"])})

    # If we are working with students, add additional parameters.
    if "sync_type" in options:
        if options["sync_type"] == "Students":
            print("Getting Veracross Students (Current)")

            # Add a grade level filter
            if "grade_level" in options["sync_filters"]:
                if options["sync_filters"]["grade_level"]:
                    if "other" in options["sync_filters"]["grade_level"]:
                        # Append non-standard grades to the grade_level param. 20-30
                        param.update({"grade_level": ",".join(str(x) for x in list(range(20, 30)))})
                    else:
                        param.update({"grade_level": options["sync_filters"]["grade_level"]})

            # Limit to only current students
            param.update({"option": "2"})

            # Show our parameters to console
            print("VC Parameters: " + str(param))

            # Get Veracross data for students
            vcdata = vc.pull("students", parameters=param)

            # Get Lightspeed id number that matches customer_type Student
            try:
                ls_customer_types = get_ls_customer_types(ls)
                ls_customerTypeID = ls_customer_types["Student"]
            except:
                print("Unable to assign customer type from Lightspeed")
                sys.exit(2)

        # Determine if we want FacultyStaff from VC
        if options["sync_type"] == "Faculty Staff":

            print("Getting Veracross Faculty Staff (Faculty and Staff)")
            # Limit to roles 1 & 2 in VC Api.
            param.update({"roles": "1,2"})

            # Show parameters to debug log
            print("VC Parameters: " + str(param), "debug")

            # Get Veracross data for Faculty Staff
            vcdata = vc.pull("facstaff", parameters=param)

            # Determine what Lightspeed customer id number for FacStaff
            try:
                ls_customer_types = get_ls_customer_types(ls)
                ls_customerTypeID = ls_customer_types["FacultyStaff"]
            except:
                print("Unable to assign customer type from Lightspeed")
                sys.exit(2)

    # User did not select a user type
    else:
        print("sync_type of 'Faculty Staff' or 'Students' not found in sync options json file.")
        sys.exit(2)

    if vcdata:
        # Loop through the data from VC.
        for i in vcdata:

            print("Processing VC Record {}".format(i["person_pk"]))

            # Get household data for this person
            hh = vc.pull("households/" + str(i["household_fk"]))
            h = hh["household"]

            # Set search parameters for lightspeed and see if we find someone in LS.
            lsparam = dict(load_relations='all', limit=1, companyRegistrationNumber=str(i["person_pk"]))
            check_current = ls.get("Customer", parameters=lsparam)

            # Format data to how it should look. First name will format later.
            vc_formatted = {'Customer':
                                {'firstName': '',
                                 'lastName': i["last_name"],
                                 'companyRegistrationNumber': i["person_pk"],
                                 'customerTypeID': ls_customerTypeID,
                                 'Contact': {
                                     'custom': i["person_pk"],
                                     'noEmail': 'false',
                                     'noPhone': 'false',
                                     'noMail': 'false',
                                     'Emails': {
                                         'ContactEmail': {
                                             'address': i["email_1"],
                                             'useType': 'Primary'
                                         }
                                     },
                                     'Addresses': {
                                         'ContactAddress': {
                                             'address1': h["address_1"],
                                             'address2': h["address_2"],
                                             'city': h["city"],
                                             'state': h["state_province"],
                                             'zip': h["postal_code"],
                                             'country': h["country"],
                                             'countryCode': '',
                                             'stateCode': ''
                                         }
                                     }
                                 },
                                 'CreditAccount': {
                                     'creditLimit': str(c["import_options_creditamount"]) + '.00'
                                 },
                                 'CustomFieldValues': {
                                     'CustomFieldValue': [{
                                         'customFieldID': c["import_options_veracrossid"],
                                         'value': i["person_pk"]
                                     }, {
                                         'customFieldID': c["import_options_lastsync"],
                                         'value': str(datetime.datetime.now())
                                     }
                                     ]}
                                 }
                            }

            # Update data to use correct nick name format from VC.
            # Added becuase of bug in VC API where sometimes one is returned over other.
            if 'nick_first_name' in i:
                vc_formatted['Customer']['firstName'] = i['nick_first_name']
            elif 'first_nick_name' in i:
                vc_formatted['Customer']['firstName'] = i['first_nick_name']

            # Did we find a record in Lighspeed to sync to?
            if len(check_current["Customer"]) >= 1:

                # Create two dictionaries one for VC and the other for LS
                # We will see if they match later.
                vc_person = dict()
                ls_customer = dict()

                # Format VC Data for comparison
                vc_person["personpk"] = str(i["person_pk"])
                vc_person["last_name"] = i["last_name"]
                if 'nick_first_name' in i:
                    vc_person["first_name"] = i['nick_first_name']
                elif 'first_nick_name' in i:
                    vc_person["first_name"] = i['first_nick_name']

                # Handle missing email
                if i["email_1"] is None:
                    vc_person["email"] = ''
                else:
                    vc_person["email"] = i["email_1"]

                vc_person["address_1"] = h["address_1"]
                if h["address_2"] is None:
                    vc_person["address_2"] = ''
                else:
                    vc_person["address_2"] = h["address_2"]
                vc_person["city"] = h["city"]
                vc_person["zip"] = h["postal_code"]
                vc_person["state"] = h["state_province"]

                # Format LS Data for comparison
                try:
                    ls_customer["personpk"] = str(check_current["Customer"]["Contact"]["custom"])
                except:
                    ls_customer["personpk"] = ""

                ls_customer["last_name"] = check_current["Customer"]["lastName"]
                ls_customer["first_name"] = check_current["Customer"]["firstName"]

                # Handle missing email addresses.
                try:
                    ls_customer["email"] = check_current["Customer"]["Contact"]["Emails"]["ContactEmail"]["address"]
                except:
                    ls_customer["email"] = ''

                # Handle missing mailing addresses
                try:
                    ls_customer["address_1"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"][
                        "address1"]
                    ls_customer["address_2"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"][
                        "address2"]
                    ls_customer["city"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"]["city"]
                    ls_customer["zip"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"]["zip"]
                    ls_customer["state"] = check_current["Customer"]["Contact"]["Addresses"]["ContactAddress"]["state"]
                except:
                    ls_customer["address_1"] = ''
                    ls_customer["address_2"] = ''
                    ls_customer["city"] = ''
                    ls_customer["zip"] = ''
                    ls_customer["state"] = ''

                # Compare the data. Are the two dictionaries the same...
                if "sync_force" in c:
                    if c["sync_force"]:
                        force = True
                    else:
                        force = False
                else:
                    force = False

                if not ls_customer == vc_person or force:
                    print("Updating customer {} {}.".format(vc_formatted['Customer']['firstName'],
                                                                            vc_formatted['Customer']['lastName']))
                    vc_formatted['Customer']['customerID'] = check_current['Customer']['customerID']
                    ls.update("Customer/" + vc_formatted['Customer']['customerID'], vc_formatted["Customer"])
                else:
                    print("Record {} {} already up to date.".format(vc_formatted['Customer']['firstName'],
                                                                                    vc_formatted['Customer']['lastName']))
            else:
                # Add new user when not found in LS
                print("Adding new Lightspeed Customer for {} {}".format(
                    vc_formatted['Customer']['firstName'],
                    vc_formatted['Customer']['lastName']))
                try:
                    new_customer = ls.create("Customer", vc_formatted["Customer"])
                    print("New Customer # {} Added: {} {}".format(new_customer['Customer']['customerID'],
                                                                new_customer['Customer']['firstName'],
                                                                new_customer['Customer']['lastName']))
                except:
                    print("Unable to add new Lightspeed Customer for {} {}".format(
                        vc_formatted['Customer']['firstName'],
                        vc_formatted['Customer']['lastName']))


def main(argv):
    operation = ""
    options = ""
    config_file =""

    try:
        opts, args = getopt.getopt(argv, "sc:o:h", ["sync", "config=", "options=", "help"])
    except getopt.GetoptError:
        print('main.py --help')
        sys.exit(2)
    for opt, arg in opts:
        if opt == '--help':
            print('/usr/local/bin/python3 main.py --sync --options=/path/to/options_json.json')
            sys.exit()
        elif opt in ("-s", "--sync"):
            operation = "sync"
        elif opt in ("-o", "--options"):
            options = load_json(arg)
        elif opt in ("-c", "--config"):
            config = load_json(arg)

    if operation == "sync":
        if options and config:
            sync_ls_vc(config, options)
        else:
            print("Parameter options or config missing.")
            sys.exit(2)


if __name__ == '__main__':
    main(sys.argv[1:])

