-- Shows the product line and trademark notice at the top of this plug-in's page in Lightroom's Plug-in Manager.
local LrView = import 'LrView'

local NOTICE = 'Virten Studio — Companion Workflow for Adobe® Lightroom® Classic Catalogs.\n\n'
	.. 'Adobe and Lightroom are either registered trademarks or trademarks of Adobe Inc. in the United States and/or '
	.. 'other countries. Virten Studio is an independent product and is not affiliated with, sponsored by, or endorsed '
	.. 'by Adobe Inc.\n\n'
	.. 'The plug-in applies the edits files Virten Studio writes (Library > Plug-in Extras > Apply Virten Studio Edits...). '
	.. 'Licence and open-source notices: Virten Studio > Settings > About & Open-Source Licenses.'

return {
	sectionsForTopOfDialog = function(f, _)
		return {
			{
				title = 'Virten Studio',
				f:row {
					f:static_text {
						title = NOTICE,
						fill_horizontal = 1,
						width_in_chars = 80,
						height_in_lines = 7,
					},
				},
			},
		}
	end,
}
