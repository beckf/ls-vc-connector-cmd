# Veracross and LightspeedHQ POS Sync Connector CommandLine

This is a python script developed to provide integration between Veracross and Lightspeed. 
Many of the features offered here will be mirrored from the 
[LSVCConnector](https://github.com/beckf/lightspeed-vc-connector/wiki "LSVCConnector") PyQT app.

This script can be run as python in its own virtualenv or by using the pyinstaller binary found in 
[releases](https://github.com/beckf/ls-vc-connector-cmd/releases).

### <a name="getting-started"></a>How to Get Started
Export all of your settings from LSVCConnector using version >= 1.52.  
On the Settings Tab, click Export Settings.

**Keep this file safe as it contains your API credentials.**

Download the latest release from releases and uncompress.

You can specify how to sync records using a json file as input, directly using commandline switches, 
or a mix of both.

Sample JSON Files:

All Students
```
{
  "sync_type": "Students",
  "sync_force": false,
  "sync_delete_missing": false,
  "sync_filters": {
    "after_date": "",
    "grade_level": ""
  }
}
```

Faculty records updated after 12-02-2022
```
{
  "sync_type": "Faculty Staff",
  "sync_force": false,
  "sync_delete_missing": false,
  "sync_filters": {
    "after_date": "2022-12-02",
    "grade_level": ""
  }
}
```

Then execute using:
```angular2html
/path/to/lsvcconnector-cmd --sync --config=config.json --sync_json=my_input_file.json
```

You can also mix cdm switches with json.  The switches will override the json file.

```angular2html
/path/to/lsvcconnector-cmd --sync --config=config.json --sync_json=my_input_file.json --sync_type="Students" --filter_after_date="2022-12-01"
```

