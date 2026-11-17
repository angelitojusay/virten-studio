-- Minimal fake Lightroom SDK that records what the plugin does.
LOG = { applied = 0, ai = 0, ratings = 0, picks = 0, labels = 0, masks = 0, crops = 0, looks = 0, messages = {}, sample = nil }
local photo_mt = {}
photo_mt.__index = photo_mt
function photo_mt:applyDevelopSettings(s, name)
  LOG.applied = LOG.applied + 1; LOG.history = name
  for _, g in ipairs(s.MaskGroupBasedCorrections or {}) do
    assert(type(g.CorrectionMasks) == 'table', 'mask structure not decoded')
    local m = g.CorrectionMasks[1]
    if m.What == 'Mask/Gradient' then
      assert(type(m.ZeroX) == 'number' and type(m.FullX) == 'number', 'gradient points not decoded')
      LOG.gradients = (LOG.gradients or 0) + 1
      LOG.gradient_sample = string.format('%s %.2f,%.2f->%.2f,%.2f temp=%s', g.CorrectionName, m.ZeroX, m.ZeroY, m.FullX, m.FullY, tostring(g.LocalTemperature))
    else
      assert(m.What == 'Mask/Image', 'unknown mask type ' .. tostring(m.What))
      LOG.masks = LOG.masks + 1
      LOG.sample = g.CorrectionName .. ' subtype=' .. tostring(m.MaskSubType)
    end
  end
  if s.CropAngle then LOG.crops = LOG.crops + 1 end
  if s.SplitToningShadowHue then LOG.looks = LOG.looks + 1 end
  assert(type(s.ToneCurvePV2012 or {}) == 'table')
end
function photo_mt:setRawMetadata(k, v)
  if k == 'rating' then LOG.ratings = LOG.ratings + 1 elseif k == 'pickStatus' then assert(v == -1); LOG.picks = LOG.picks + 1 else LOG.labels = LOG.labels + 1 end
end
function photo_mt:updateAISettings() LOG.ai = LOG.ai + 1 end
-- Keywords and collections (for assisted-cull files)
local kw_mt = {}; kw_mt.__index = kw_mt
function kw_mt:getName() return self.name end
function kw_mt:getParent() return self.parent end
KEYWORDS = {}
local function kwPath(k) local p = {} while k do table.insert(p, 1, k.name) k = k.parent end return table.concat(p, '|') end
function photo_mt:getRawMetadata(k) assert(k == 'keywords'); local out = {} for kw in pairs(self.kws or {}) do out[#out + 1] = kw end return out end
function photo_mt:addKeyword(kw) self.kws = self.kws or {}; self.kws[kw] = true end
function photo_mt:removeKeyword(kw) self.kws[kw] = nil end
function photo_mt:keywordPaths() local t = {} for kw in pairs(self.kws or {}) do t[#t + 1] = kwPath(kw) end table.sort(t) return t end
local coll_mt = {}; coll_mt.__index = coll_mt
function coll_mt:getName() return self.name end
function coll_mt:addPhotos(ps) for _, p in ipairs(ps) do self.photos[p] = true end end
function coll_mt:removeAllPhotos() self.photos = {} end
function coll_mt:count() local n = 0 for _ in pairs(self.photos) do n = n + 1 end return n end
local set_mt = {}; set_mt.__index = set_mt
function set_mt:getChildCollections() local t = {} for _, c in pairs(self.colls) do t[#t + 1] = c end return t end
SETS = {}
local catalog = {}
function catalog:createKeyword(name, syn, includeOnExport, parent, returnExisting)
  assert(includeOnExport == false, 'cull keywords must not be exported')
  assert(returnExisting == true)
  local key = (parent and kwPath(parent) .. '|' or '') .. name
  KEYWORDS[key] = KEYWORDS[key] or setmetatable({ name = name, parent = parent }, kw_mt)
  return KEYWORDS[key]
end
function catalog:createCollectionSet(name, parent, returnExisting)
  local key = (parent and parent.name .. '>' or '') .. name
  SETS[key] = SETS[key] or setmetatable({ name = name, colls = {} }, set_mt)
  return SETS[key]
end
function catalog:createCollection(name, set, returnExisting)
  set.colls[name] = set.colls[name] or setmetatable({ name = name, photos = {} }, coll_mt)
  return set.colls[name]
end
local PHOTOS = {}
function catalog:getPath() return 'C:/fake/catalog.lrcat' end
function catalog:findPhotoByUuid(u) PHOTOS[u] = PHOTOS[u] or setmetatable({ uuid = u }, photo_mt); return PHOTOS[u] end
function PHOTO(u) return PHOTOS[u] end
function catalog:findPhotoByPath(p) return nil end
function catalog:withWriteAccessDo(name, fn, opts) fn() end
local function readFile(p) local f = io.open(p, 'rb'); local t = f:read('*a'); f:close(); return t end
local SDK = {
  LrApplication = { activeCatalog = function() return catalog end },
  LrDialogs = { runOpenPanel = function() return { EDITS_FILE } end, confirm = function(a, b, ok, cancel, other) LOG.confirm = b; LOG.buttons = tostring(ok) .. ' / ' .. tostring(cancel) .. ' / ' .. tostring(other); return CONFIRM_CHOICE or 'ok' end,
                message = function(t, m) LOG.messages[#LOG.messages + 1] = m end },
  LrFileUtils = { readFile = readFile, exists = function() return false end, files = function() return function() end end,
                  move = function(a, b) os.rename(a, b) end },
  LrPathUtils = { child = function(a, b) return a .. '/' .. b end, parent = function(p) return p:match('(.*)[/\\]') end,
                  extension = function(p) return p:match('%.([^.]+)$') end },
  LrProgressScope = setmetatable({}, { __call = function() return { isCanceled = function() return false end,
                     setPortionComplete = function() end, done = function() end } end }),
  LrFunctionContext = { callWithContext = function(n, fn) fn({}) end },
  LrTasks = { startAsyncTask = function(fn) fn() end, pcall = function(f, ...) return pcall(f, ...) end, yield = function() end },
}
function import(name) return assert(SDK[name], 'unknown SDK module ' .. name) end
function REPORT()
  return string.format('buttons: ' .. tostring(LOG.buttons) .. '\nconfirm: %s\napplied=%d masks=%d crops=%d looks=%d updateAISettings=%d ratings=%d rejected=%d labels=%d history=%s\nmask sample: %s\ngradients=%d sample: %s\nfinal message: %s',
    tostring(LOG.confirm):gsub('\n', ' '), LOG.applied, LOG.masks, LOG.crops, LOG.looks, LOG.ai, LOG.ratings, LOG.picks, LOG.labels,
    tostring(LOG.history), tostring(LOG.sample), LOG.gradients or 0, tostring(LOG.gradient_sample), tostring(LOG.messages[#LOG.messages]):gsub('\n', ' | '))
end