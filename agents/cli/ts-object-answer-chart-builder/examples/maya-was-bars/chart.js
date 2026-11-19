// Search: [sales] [item type] [date].yearly. Bars for the latest year, a dashed ghost of the year before.
const MAYA = 'https://cdn.jsdelivr.net/npm/mayacharts@0.18.1/dist/maya.core.global.js';
const SRI = 'sha384-KZQbG8OHSEU86UWT5Pp3LATC64UAhHxwg1UMKN/lZtsu02CeDifcSVWCewQO2h/6'; // the doctor prints it beside the version
const go = () => maya.host.thoughtspot(viz, { type: 'bar', horizontal: true, x: 'Item Type', y: 'Total Sales', was: { by: 'Year(Date)' }, sort: 'desc', select: true,
  format: { 'Total Sales': { style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 1 }, 'Year(Date)': 'year' }, titles: { 'Item Type': 'Item type' },
  title: '{max.x} leads with {max.y}', text: { noData: 'No rows yet: bind [sales] [item type] [date].yearly' } });
if (window.maya?.host) go(); else { const s = document.querySelector('script[src="' + MAYA + '"]') ?? document.head.appendChild(Object.assign(document.createElement('script'), { src: MAYA, integrity: SRI, crossOrigin: 'anonymous' })); s.addEventListener('load', go); s.addEventListener('error', () => { (document.getElementById('chart') ?? document.body).textContent = 'MayaCharts could not load from ' + MAYA; viz?.events?.emitRenderCompletedEvent?.(); }); }
