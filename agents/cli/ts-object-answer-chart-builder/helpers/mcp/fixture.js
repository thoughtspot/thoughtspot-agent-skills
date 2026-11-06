// A real-data fixture, read only: the tile's exact search, as the column names and rows it returns. The caller
// writes them to <RUNS>/<slug>/sample-data.json as { schema, rows } (references/library-contract.md section 4).
const MODEL = __MODEL__, SEARCH = __SEARCH__, ROWS = __ROWS__;
const q = await ts.post('/api/rest/2.0/searchdata', { logical_table_identifier: MODEL, query_string: SEARCH, record_size: ROWS });
const c = q.status === 200 && q.body && q.body.contents && q.body.contents[0];
if (!c || !Array.isArray(c.column_names) || !c.column_names.length) return { refused: 'search failed: ' + SEARCH, raw: JSON.stringify(q.body).slice(0, 600) };
return JSON.stringify({ columns: c.column_names, rows: c.data_rows || [], total: c.record_count });
