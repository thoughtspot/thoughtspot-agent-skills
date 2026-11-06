// Step 0 round 2, read only: one model's columns (name, ATTRIBUTE or MEASURE, data type), by guid.
const MODEL = __MODEL__;
const r = await ts.post('/api/rest/2.0/metadata/search', { metadata: [{ type: 'LOGICAL_TABLE', identifier: MODEL }], include_details: true, record_size: 2 });
const m = Array.isArray(r.body) && r.body.length === 1 ? r.body[0] : null;
if (!m || String(m.metadata_id).toLowerCase() !== MODEL.toLowerCase()) return { refused: 'no model with guid ' + MODEL, http: r.status };
const cols = ((m.metadata_detail || {}).columns || []).map((c) => ({ name: (c.header || {}).name || c.name, type: c.type, dataType: c.dataType || c.data_type }));
return { model: m.metadata_name, guid: m.metadata_id, columns: cols };
