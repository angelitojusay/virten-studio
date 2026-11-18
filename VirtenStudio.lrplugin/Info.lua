-- Virten Studio — Companion Workflow for Adobe® Lightroom® Classic Catalogs.
-- Adobe and Lightroom are either registered trademarks or trademarks of Adobe Inc. in the United States and/or other
-- countries. Virten Studio is an independent product and is not affiliated with, sponsored by, or endorsed by Adobe Inc.
return {
	LrSdkVersion = 10.0,
	LrSdkMinimumVersion = 6.0,
	LrToolkitIdentifier = 'com.angelitojusay.virtenstudio',
	LrPluginName = 'Virten Studio',
	LrPluginInfoProvider = 'PluginInfoProvider.lua',
	LrLibraryMenuItems = {
		{ title = 'Apply Virten Studio Edits...', file = 'ApplyEdits.lua' },
	},
	LrExportMenuItems = {
		{ title = 'Apply Virten Studio Edits...', file = 'ApplyEdits.lua' },
	},
	VERSION = { major = 1, minor = 6, revision = 2, build = 1 },
}
