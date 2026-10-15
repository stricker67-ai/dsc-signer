#!/usr/bin/env python3
"""Install "Sign with DSC" Quick Actions into ~/Library/Services.

  * Finder: right-click one or more PDFs -> Quick Actions -> Sign with DSC
  * PDF Expert (if installed): PDF Expert menu -> Services -> Sign with DSC
    (signs the document that is open in PDF Expert)

Both run dsc-sign-pdfexpert, which opens dsc-sign-gui with the file(s) and
then opens each *_signed.pdf once it has been written.

Usage: make_quick_actions.py [path/to/dsc-sign-pdfexpert]
       (default: ~/.local/bin/dsc-sign-pdfexpert)
"""
import os
import plistlib
import shlex
import subprocess
import sys
import uuid

HOME = os.path.expanduser("~")
SERVICES = os.path.join(HOME, "Library", "Services")
NOTHING = "com.apple.Automator.nothing"
FILES = "com.apple.Automator.fileSystemObject"
FINDER = ("com.apple.finder", "/System/Library/CoreServices/Finder.app")
PDF_EXPERT = ("com.readdle.PDFExpert-Mac", "/Applications/PDF Expert.app")


def _arg(name, uid, default, kind="0"):
    return {"default value": default, "name": name, "required": "0", "type": kind, "uuid": uid}


def run_shell_action(command):
    """One Automator 'Run Shell Script' action (zsh, input passed as arguments)."""
    return {
        "action": {
            "AMAccepts": {"Container": "List", "Optional": True, "Types": ["com.apple.cocoa.string"]},
            "AMActionVersion": "2.0.3",
            "AMApplication": ["Automator"],
            "AMParameterProperties": {k: {} for k in
                                      ("COMMAND_STRING", "CheckedForUserDefaultShell", "inputMethod", "shell", "source")},
            "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
            "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
            "ActionName": "Run Shell Script",
            "ActionParameters": {
                "COMMAND_STRING": command,
                "CheckedForUserDefaultShell": True,
                "inputMethod": 1,          # pass input as arguments ("$@")
                "shell": "/bin/zsh",
                "source": "",
            },
            "BundleIdentifier": "com.apple.RunShellScript",
            "CFBundleVersion": "2.0.3",
            "CanShowSelectedItemsWhenRun": False,
            "CanShowWhenRun": True,
            "Category": ["AMCategoryUtilities"],
            "Class Name": "RunShellScriptAction",
            "InputUUID": str(uuid.uuid4()).upper(),
            "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
            "OutputUUID": str(uuid.uuid4()).upper(),
            "UUID": str(uuid.uuid4()).upper(),
            "UnlocalizedApplications": ["Automator"],
            "arguments": {
                "0": _arg("inputMethod", "0", 0),
                "1": _arg("CheckedForUserDefaultShell", "1", False),
                "2": _arg("source", "2", ""),
                "3": _arg("COMMAND_STRING", "3", ""),
                "4": _arg("shell", "4", "/bin/sh"),
            },
            "conversionLabel": 0,
            "isViewVisible": 1,
            "location": "309.000000:305.000000",
            "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/Base.lproj/main.nib",
        },
        "isViewVisible": 1,
    }


def write_service(name, app, input_type, send_file_types, command):
    app_id, app_path = app
    doc = {
        "AMApplicationBuild": "534",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [run_shell_action(command)],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleID": app_id,
            "applicationBundleIDsByPath": {app_path: app_id},
            "applicationPath": app_path,
            "applicationPaths": [app_path],
            "inputTypeIdentifier": input_type,
            "outputTypeIdentifier": NOTHING,
            "presentationMode": 15,
            "processesInput": False,
            "serviceApplicationBundleID": app_id,
            "serviceApplicationPath": app_path,
            "serviceInputTypeIdentifier": input_type,
            "serviceOutputTypeIdentifier": NOTHING,
            "serviceProcessesInput": False,
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }
    service = {
        "NSBackgroundColorName": "background",
        "NSIconName": "NSActionTemplate",
        "NSMenuItem": {"default": "Sign with DSC"},
        "NSMessage": "runWorkflowAsService",
        "NSRequiredContext": {"NSApplicationIdentifier": app_id},
    }
    if send_file_types:
        service["NSSendFileTypes"] = send_file_types
    contents = os.path.join(SERVICES, f"{name}.workflow", "Contents")
    os.makedirs(contents, exist_ok=True)
    with open(os.path.join(contents, "document.wflow"), "wb") as f:
        plistlib.dump(doc, f)
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump({"NSServices": [service]}, f)
    print("installed", os.path.dirname(contents))


def main():
    helper = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HOME, ".local", "bin", "dsc-sign-pdfexpert")
    if not os.access(helper, os.X_OK):
        sys.exit(f"helper not found or not executable: {helper}")
    command = f'{shlex.quote(helper)} "$@"'
    write_service("Sign with DSC (Finder)", FINDER, FILES, ["com.adobe.pdf"], command)
    if os.path.isdir(PDF_EXPERT[1]):
        write_service("Sign with DSC", PDF_EXPERT, NOTHING, None, command)
    # Re-read the Services list so the new entries show up without logging out.
    subprocess.run(["/System/Library/CoreServices/pbs", "-update"], check=False)


if __name__ == "__main__":
    main()
