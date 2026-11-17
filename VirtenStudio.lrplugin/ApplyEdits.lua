--[[ Applies the develop settings in a .virten file (written by the Virten Studio app)
     to the matching photos in the active catalog, one history step per photo.
     Photos that received AI masks are then refreshed with photo:updateAISettings()
     so Lightroom computes the subject/sky/skin selections itself. ]]

local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrFileUtils = import 'LrFileUtils'
local LrFunctionContext = import 'LrFunctionContext'
local LrPathUtils = import 'LrPathUtils'
local LrProgressScope = import 'LrProgressScope'
local LrTasks = import 'LrTasks'

-- Minimal JSON decoder for nested settings such as MaskGroupBasedCorrections.
local function utf8char(code)
	if code < 0x80 then return string.char(code) end
	if code < 0x800 then
		return string.char(0xC0 + math.floor(code / 0x40), 0x80 + code % 0x40)
	end
	return string.char(0xE0 + math.floor(code / 0x1000), 0x80 + math.floor(code / 0x40) % 0x40, 0x80 + code % 0x40)
end

local function decodeJSON(s)
	local pos = 1
	local value
	local function ws() pos = string.find(s, '[^ \t\r\n]', pos) or (#s + 1) end
	local escapes = { b = '\b', f = '\f', n = '\n', r = '\r', t = '\t' }
	local function str()
		pos = pos + 1
		local buf = {}
		while pos <= #s do
			local c = string.sub(s, pos, pos)
			if c == '"' then pos = pos + 1; return table.concat(buf) end
			if c == '\\' then
				local n = string.sub(s, pos + 1, pos + 1)
				if n == 'u' then
					buf[#buf + 1] = utf8char(tonumber(string.sub(s, pos + 2, pos + 5), 16))
					pos = pos + 6
				else
					buf[#buf + 1] = escapes[n] or n
					pos = pos + 2
				end
			else
				buf[#buf + 1] = c
				pos = pos + 1
			end
		end
		error('unterminated string')
	end
	value = function()
		ws()
		local c = string.sub(s, pos, pos)
		if c == '{' then
			pos = pos + 1
			local t = {}
			ws()
			if string.sub(s, pos, pos) == '}' then pos = pos + 1; return t end
			while true do
				ws()
				local k = str()
				ws(); pos = pos + 1 -- ':'
				t[k] = value()
				ws()
				local d = string.sub(s, pos, pos); pos = pos + 1
				if d == '}' then return t end
			end
		elseif c == '[' then
			pos = pos + 1
			local t = {}
			ws()
			if string.sub(s, pos, pos) == ']' then pos = pos + 1; return t end
			while true do
				t[#t + 1] = value()
				ws()
				local d = string.sub(s, pos, pos); pos = pos + 1
				if d == ']' then return t end
			end
		elseif c == '"' then
			return str()
		elseif string.sub(s, pos, pos + 3) == 'true' then
			pos = pos + 4; return true
		elseif string.sub(s, pos, pos + 4) == 'false' then
			pos = pos + 5; return false
		elseif string.sub(s, pos, pos + 3) == 'null' then
			pos = pos + 4; return nil
		end
		local num = string.match(s, '^-?%d+%.?%d*[eE]?[-+]?%d*', pos)
		if not num then error('bad JSON at ' .. pos) end
		pos = pos + #num
		return tonumber(num)
	end
	return value()
end

local function parseEdits(path)
	local text = LrFileUtils.readFile(path)
	-- Files from AutoStyle (the app's earlier name) start with AUTOSTYLE and still work.
	if not text or not (string.find(text, '^VIRTEN\t') or string.find(text, '^AUTOSTYLE\t')) then
		return nil, 'This is not a Virten Studio edits file.'
	end
	local profile, edits, cur, kind, title = 'Virten Studio', {}, nil, nil, nil
	for line in string.gmatch(text, '[^\r\n]+') do
		local tag, a, b = string.match(line, '^(%u+)\t?([^\t]*)\t?(.*)$')
		if tag == 'PROFILE' then
			profile = a
		elseif tag == 'KIND' then
			kind = a
		elseif tag == 'TITLE' then
			title = a
		elseif tag == 'PHOTO' then
			cur = { uuid = a, path = b, settings = {} }
		elseif tag == 'END' and cur then
			edits[#edits + 1] = cur
			cur = nil
		elseif cur and tag == 'N' then
			cur.settings[a] = tonumber(b)
		elseif cur and tag == 'S' then
			cur.settings[a] = b
		elseif cur and tag == 'B' then
			cur.settings[a] = (b == 'true')
		elseif cur and tag == 'C' then
			local list = {}
			for n in string.gmatch(b, '[^,]+') do list[#list + 1] = tonumber(n) end
			cur.settings[a] = list
		elseif cur and tag == 'J' then
			local ok, v = pcall(decodeJSON, b)
			if ok then cur.settings[a] = v end
		end
	end
	return { profile = profile, edits = edits, kind = kind, title = title }
end

-- ---------------------------------------------------------------- assisted cull
-- Cull files carry keywords and collection names per photo. They go under the "Virten Cull" keyword (not included
-- on export) and a "Virten Cull" collection set. Ratings, flags, labels and develop settings are never touched.
local CULL_ROOT = 'Virten Cull'

local function splitList(s)
	local t = {}
	for item in string.gmatch(s or '', '[^;]+') do t[#t + 1] = item end
	return t
end

local function underCullRoot(kw)
	local k = kw
	while k do
		local parent = k:getParent()
		if parent == nil then return k:getName() == CULL_ROOT end
		k = parent
	end
	return false
end

local function applyCull(context, catalog, file, data, targets, missing)
	local msg = string.format('Add cull suggestions to %d photo(s)?\n\n'
		.. 'Virten Studio adds keywords under "%s" (left out when you export) and collections in the "%s" set. '
		.. 'Your ratings, flags, color labels and edits are not changed. Earlier suggestions on these photos are replaced.',
		#targets, CULL_ROOT, CULL_ROOT)
	if missing > 0 then msg = msg .. string.format('\n\n%d photo(s) were not found in this catalog and will be skipped.', missing) end
	if LrDialogs.confirm('Virten Studio', msg, 'Add Suggestions', 'Cancel') ~= 'ok' then return end

	local title = data.title or 'Cull'
	local needKw, needColl = {}, {}
	for _, t in ipairs(targets) do
		t.kws = splitList(t.settings._Keywords)
		t.colls = splitList(t.settings._Collections)
		for _, k in ipairs(t.kws) do needKw[k] = true end
		for _, c in ipairs(t.colls) do needColl[c] = true end
	end

	-- Keywords and collections are created first, then looked up again (returnExisting) when photos are added.
	local function resolve()
		local kw = {}
		local root = catalog:createKeyword(CULL_ROOT, {}, false, nil, true)
		for path in pairs(needKw) do
			local parent, sofar = root, nil
			for part in string.gmatch(path, '[^|]+') do
				sofar = sofar and (sofar .. '|' .. part) or part
				if not kw[sofar] then kw[sofar] = catalog:createKeyword(part, {}, false, parent, true) end
				parent = kw[sofar]
			end
		end
		local set = catalog:createCollectionSet(CULL_ROOT, nil, true)
		local sub = catalog:createCollectionSet(title, set, true)
		local coll = {}
		for name in pairs(needColl) do coll[name] = catalog:createCollection(name, sub, true) end
		-- Also the collections a previous run of this cull made, so they can be emptied.
		for _, c in ipairs(sub:getChildCollections()) do coll[c:getName()] = coll[c:getName()] or c end
		return kw, coll
	end
	catalog:withWriteAccessDo('Virten Cull setup', function() resolve() end, { timeout = 60 })

	local progress = LrProgressScope { title = 'Virten Studio: adding cull suggestions', functionContext = context }
	local kw, coll
	catalog:withWriteAccessDo('Virten Cull collections', function()
		kw, coll = resolve()
		for _, c in pairs(coll) do LrTasks.pcall(function() c:removeAllPhotos() end) end
	end, { timeout = 120 })

	local batch, done, failed = 100, 0, 0
	for first = 1, #targets, batch do
		if progress:isCanceled() then break end
		catalog:withWriteAccessDo('Virten Cull keywords', function()
			for i = first, math.min(first + batch - 1, #targets) do
				local t = targets[i]
				local ok = LrTasks.pcall(function()
					for _, old in ipairs(t.photo:getRawMetadata('keywords') or {}) do
						if underCullRoot(old) then t.photo:removeKeyword(old) end
					end
					for _, k in ipairs(t.kws) do
						if kw[k] then t.photo:addKeyword(kw[k]) end
					end
				end)
				if ok then done = done + 1 else failed = failed + 1 end
			end
		end, { timeout = 120 })
		progress:setPortionComplete(math.min(first + batch - 1, #targets), #targets)
		LrTasks.yield()
	end

	local inColl = {}
	for _, t in ipairs(targets) do
		for _, c in ipairs(t.colls) do
			inColl[c] = inColl[c] or {}
			inColl[c][#inColl[c] + 1] = t.photo
		end
	end
	if not progress:isCanceled() then
		catalog:withWriteAccessDo('Virten Cull collections', function()
			for name, photos in pairs(inColl) do
				if coll[name] then coll[name]:addPhotos(photos) end
			end
		end, { timeout = 120 })
	end
	local canceled = progress:isCanceled()
	progress:done()

	if done == #targets then LrFileUtils.move(file, file .. '.applied') end
	local counts = {}
	for name, photos in pairs(inColl) do counts[#counts + 1] = string.format('%s: %d', name, #photos) end
	table.sort(counts)
	local summary = string.format('Added suggestions to %d photo(s).', done)
	if failed > 0 then summary = summary .. string.format('\n%d photo(s) failed.', failed) end
	if canceled then summary = summary .. '\nStopped before finishing; run it again to finish.' end
	if #counts > 0 then summary = summary .. '\n\nCollections (in ' .. CULL_ROOT .. ' > ' .. title .. '):\n' .. table.concat(counts, '\n') end
	summary = summary .. '\n\nTip: in the Library filter bar, filter by the "' .. CULL_ROOT .. '" keywords, or open the collections. '
		.. 'To remove all suggestions later, delete the "' .. CULL_ROOT .. '" keyword and collection set.'
	LrDialogs.message('Virten Studio', summary, 'info')
end

local function chooseFile(catalog)
	local catalogDir = LrPathUtils.parent(catalog:getPath())
	local folder = LrPathUtils.child(catalogDir, 'Virten Studio')
	local pending = {}
	for _, dir in ipairs({ folder, LrPathUtils.child(catalogDir, 'AutoStyle') }) do
		if LrFileUtils.exists(dir) then
			for f in LrFileUtils.files(dir) do
				local ext = LrPathUtils.extension(f)
				if ext == 'virten' or ext == 'autostyle' then pending[#pending + 1] = f end
			end
		end
	end
	if #pending == 1 then return pending[1] end
	local picked = LrDialogs.runOpenPanel {
		title = 'Choose Virten Studio edits to apply',
		canChooseFiles = true, canChooseDirectories = false, allowsMultipleSelection = false,
		fileTypes = { 'virten', 'autostyle' },
		initialDirectory = LrFileUtils.exists(folder) and folder or nil,
	}
	return picked and picked[1]
end

LrTasks.startAsyncTask(function()
	LrFunctionContext.callWithContext('Virten Studio apply', function(context)
		local catalog = LrApplication.activeCatalog()
		local file = chooseFile(catalog)
		if not file then return end

		local data, err = parseEdits(file)
		if not data then
			LrDialogs.message('Virten Studio', err, 'critical')
			return
		end

		local targets, missing, masked = {}, 0, 0
		for _, e in ipairs(data.edits) do
			local photo = catalog:findPhotoByUuid(e.uuid) or catalog:findPhotoByPath(e.path)
			if photo then
				-- Only AI masks (Mask/Image) need Lightroom to compute anything; gradients apply as-is.
				local hasMasks = false
				for _, g in ipairs(e.settings.MaskGroupBasedCorrections or {}) do
					for _, m in ipairs(g.CorrectionMasks or {}) do
						if m.What == 'Mask/Image' then hasMasks = true end
					end
				end
				if hasMasks then masked = masked + 1 end
				targets[#targets + 1] = { photo = photo, settings = e.settings, masks = hasMasks }
			else
				missing = missing + 1
			end
		end
		if #targets == 0 then
			LrDialogs.message('Virten Studio', 'None of the photos in this file are in the open catalog. '
				.. 'Open the catalog the project was made from and try again.', 'warning')
			return
		end
		if data.kind == 'cull' then
			applyCull(context, catalog, file, data, targets, missing)
			return
		end

		local msg = string.format('Apply "%s" edits to %d photo(s)?', data.profile, #targets)
		if masked > 0 then
			msg = msg .. string.format('\n\n%d photo(s) get AI masks.\n- Apply (masks later) is fastest: Lightroom fills in each mask when you open the photo.'
				.. '\n- Apply + compute masks now computes them all up front (a few seconds per photo).', masked)
		end
		if missing > 0 then msg = msg .. string.format('\n\n%d photo(s) were not found in this catalog and will be skipped.', missing) end
		local computeMasksNow = false
		if masked > 0 then
			local choice = LrDialogs.confirm('Virten Studio', msg, 'Apply (masks later)', 'Cancel', 'Apply + compute masks now')
			if choice == 'cancel' then return end
			computeMasksNow = (choice == 'other')
		elseif LrDialogs.confirm('Virten Studio', msg, 'Apply Edits', 'Cancel') ~= 'ok' then
			return
		end

		local progress = LrProgressScope { title = 'Virten Studio: applying edits', functionContext = context }
		local historyName = 'Virten Studio: ' .. data.profile
		local batch, applied, failed = 20, 0, 0
		for first = 1, #targets, batch do
			if progress:isCanceled() then break end
			catalog:withWriteAccessDo('Virten Studio edits', function()
				for i = first, math.min(first + batch - 1, #targets) do
					local t = targets[i]
					t.ok = LrTasks.pcall(function() t.photo:applyDevelopSettings(t.settings, historyName) end)
					if t.ok then applied = applied + 1 else failed = failed + 1 end
				end
			end, { timeout = 120 })
			progress:setPortionComplete(math.min(first + batch - 1, #targets), #targets)
		end
		local canceled = progress:isCanceled()
		progress:done()

		-- Compute the AI masks (Lightroom Classic 13.3+).
		local aiDone, aiFailed, aiUnsupported = 0, 0, false
		if masked > 0 and computeMasksNow and not canceled then
			local aiProgress = LrProgressScope { title = 'Virten Studio: computing AI masks', functionContext = context }
			local todo = {}
			for _, t in ipairs(targets) do if t.ok and t.masks then todo[#todo + 1] = t end end
			for i, t in ipairs(todo) do
				if aiProgress:isCanceled() then break end
				local ok, e = LrTasks.pcall(function()
					catalog:withWriteAccessDo('Virten Studio AI masks', function() t.photo:updateAISettings() end, { timeout = 300 })
				end)
				if ok then
					aiDone = aiDone + 1
				else
					aiFailed = aiFailed + 1
					if i == 1 and string.find(tostring(e), 'updateAISettings') then aiUnsupported = true; break end
				end
				aiProgress:setPortionComplete(i, #todo)
				LrTasks.yield()
			end
			aiProgress:done()
		end

		if applied == #targets then
			LrFileUtils.move(file, file .. '.applied')
		end
		local summary = string.format('Applied edits to %d photo(s).', applied)
		if failed > 0 then summary = summary .. string.format('\n%d photo(s) failed.', failed) end
		if applied < #targets and failed == 0 then summary = summary .. '\nStopped before finishing; run it again to apply the rest.' end
		if masked > 0 and not computeMasksNow then
			summary = summary .. '\n\nLightroom will fill in the AI masks as you open each photo. If a photo shows a mask warning, '
				.. 'select the photos in Library and choose Photo > Develop Settings > Update AI Settings.'
		elseif masked > 0 then
			if aiUnsupported then
				summary = summary .. '\n\nThis Lightroom version cannot update AI masks from a plugin. Select the photos in Library and choose Photo > Develop Settings > Update AI Settings.'
			else
				summary = summary .. string.format('\nComputed AI masks for %d photo(s).', aiDone)
				if aiFailed > 0 or aiDone < masked then
					summary = summary .. '\nFor any photo still showing a mask warning, select it and choose Photo > Develop Settings > Update AI Settings.'
				end
			end
		end
		LrDialogs.message('Virten Studio', summary, 'info')
	end)
end)
