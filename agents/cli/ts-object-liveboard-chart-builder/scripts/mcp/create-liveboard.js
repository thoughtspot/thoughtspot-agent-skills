// Step 3: create the empty Liveboard, its tabs already named. A VALIDATE_ONLY import first, then the real one, and
// both statuses checked before the guid is trusted (the rule every later block follows). Send it with
// confirm_write_operations: true. A refused result means nothing was created.
const NAME = __NAME__, DESCRIPTION = __DESCRIPTION__, TABS = __TABS__;
const tml = { liveboard: { name: NAME, description: DESCRIPTION, visualizations: [], layout: { tabs: TABS.map((t) => ({ name: t, tiles: [] })) } } };
const body = { metadata_tmls: [JSON.stringify(tml)], import_policy: 'ALL_OR_NONE', create_new: true };
const first = (r) => (((r || {}).body || [])[0] || {}).response || {};
const v = first(await ts.post('/api/rest/2.0/metadata/tml/import', { ...body, import_policy: 'VALIDATE_ONLY' }));
if ((v.status || {}).status_code !== 'OK') return { refused: 'validate failed', validate: v.status };
const i = first(await ts.post('/api/rest/2.0/metadata/tml/import', body));
if ((i.status || {}).status_code !== 'OK' || !(i.header || {}).id_guid) return { refused: 'import failed', import: i.status };
return { guid: i.header.id_guid, validate: v.status, import: i.status };
