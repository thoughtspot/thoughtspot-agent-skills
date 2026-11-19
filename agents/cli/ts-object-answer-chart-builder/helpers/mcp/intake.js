// Step 0 intake, read only: the signed-in user, the org the token is bound to, the cluster name, and the models
// whose name matches the user's words (an unfiltered listing is cut off before the one the user means). Two
// models can share a name, so every later call takes the guid shown beside it.
const WORDS = __WORDS__;
const me = (await ts.get('/api/rest/2.0/auth/session/user')).body;
const sys = (await ts.get('/api/rest/2.0/system')).body;
const r = await ts.post('/api/rest/2.0/metadata/search', { metadata: [{ type: 'LOGICAL_TABLE', name_pattern: '%' + WORDS + '%' }], record_size: 50 });
const models = (Array.isArray(r.body) ? r.body : []).filter((m) => ['WORKSHEET', 'MODEL'].includes((m.metadata_header || {}).type));
return { user: me.name, org: me.current_org && me.current_org.name, cluster: sys.name, models: models.map((m) => ({ name: m.metadata_name, guid: m.metadata_id })) };
