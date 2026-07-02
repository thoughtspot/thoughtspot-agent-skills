"use strict";
const ERD = window.__ERD_DATA__ || {models: [], index: [], dropped: []};
let MODEL = ERD.models[0] || {model:{name:"(no model)",guid:"",description:""},tables:[],joins:[],formulas:{},findings:[]};

const SEV_RANK={crit:3,warn:2,info:1};
let tableById={}, findingsByTable={}, HOT_EDGES=new Set();
let adj={}, undir={};
let securedTables=[];
let LS_KEY="", savedPos={}, NOTES_KEY="", notes={};
let nodes=[], nodeById={}, edges=[];
let layoutCache={};

const NS="http://www.w3.org/2000/svg";
const $=id=>document.getElementById(id);
const svg=$("svg"),vp=$("viewport"),gEdges=$("edges"),gNodes=$("nodes"),inspector=$("inspector");
const tFind=$("findings-toggle"),colSel=$("col-mode");
const tOrth=$("orth-toggle");
let activeFilters=new Set(["all"]);

const reduce=matchMedia("(prefers-reduced-motion:reduce)").matches;
const ROW_H=20,HEAD_H=30,PAD=10;
let NODE_W=200;
let colMode="keys", layoutName="organic", notation="arrow";
let focusSet=[];
let focusMode=null;   // "neighbourhood" | "tree" | "compare" | null
let selected=null;

function worstSev(id){let w=null;(findingsByTable[id]||[]).forEach(f=>{if(!w||SEV_RANK[f.sev]>SEV_RANK[w])w=f.sev;});return w;}
// Tables referenced (by name/alias) in an RLS rule's expression, excluding the rule's
// own table. RLS is defined ON a table and may reference OTHER tables' columns; it does
// NOT propagate along joins — so this is the only "reach" a rule has beyond its owner.
const RLS_REF=/\[([^\]:]+)::/g;
function rlsRefs(expr,ownerId){const s=new Set();let m;RLS_REF.lastIndex=0;
  while((m=RLS_REF.exec(expr||"")))if(tableById[m[1]]&&m[1]!==ownerId)s.add(m[1]);return [...s];}
function connectedComponent(id){const seen=new Set([id]),q=[id];while(q.length){const n=q.shift();(undir[n]||[]).forEach(m=>{if(!seen.has(m)){seen.add(m);q.push(m);}});}return seen;}
function joinTree(id){const seen=new Set([id]),q=[id];while(q.length){const n=q.shift();(adj[n]||[]).forEach(m=>{if(!seen.has(m)){seen.add(m);q.push(m);}});}return seen;}

function visibleCols(t){
  if(colMode==="collapsed")return [];
  if(colMode==="keys")return (t.cols||[]).filter(c=>c.key);
  if(colMode==="flagged")return (t.cols||[]).filter(c=>c.flag);
  return (t.cols||[]).filter(c=>!c.hidden);
}
function nodeHeight(t){const n=visibleCols(t).length;return HEAD_H+(n?n*ROW_H+PAD:8);}

let _seed=20260627; const rnd=()=>{_seed=(_seed*1664525+1013904223)>>>0;return _seed/4294967296;};

function loadSaved(){try{return JSON.parse(localStorage.getItem(LS_KEY))||{};}catch(e){return {};}}
function persistSaved(){try{localStorage.setItem(LS_KEY,JSON.stringify(savedPos));}catch(e){}}
function loadNotes(){try{return JSON.parse(localStorage.getItem(NOTES_KEY))||{};}catch(e){return {};}}
function persistNotes(){try{localStorage.setItem(NOTES_KEY,JSON.stringify(notes));}catch(e){}}
function clearAllNotes(){if(!confirm("Remove all notes from this model?"))return;notes={};persistNotes();renderAll();if(selected&&selected.type==="table")showTable(selected.id);else if(selected&&selected.type==="edge")showEdge(selected.id);else showOverview();}
function notesSection(id){
  const val=notes[id]||"";
  return `<div class="section-label">Notes</div>
    <textarea class="notes-area" id="note-input" placeholder="Add a note…">${esc(val)}</textarea>
    <div class="notes-btns"><button id="note-save">Save note</button>${val?'<button id="note-del">Delete</button>':''}</div>`;
}
function wireNotes(id){
  const inp=$("note-input"),sv=$("note-save"),dl=$("note-del");
  if(sv)sv.onclick=()=>{const v=inp.value.trim();if(v)notes[id]=v;else delete notes[id];persistNotes();renderAll();};
  if(dl)dl.onclick=()=>{delete notes[id];persistNotes();renderAll();if(selected&&selected.type==="table")showTable(selected.id);else showEdge(selected.id);};
}
const hasAll=m=>m&&MODEL.tables.every(t=>m[t.id]);
function captureLayout(){const m={};nodes.forEach(n=>m[n.t.id]={x:Math.round(n.x),y:Math.round(n.y)});savedPos[layoutName]=m;persistSaved();updateSavedBadge();}
function updateSavedBadge(){$("saved-badge").classList.toggle("on",hasAll(savedPos[layoutName]));}

// ---- LAYOUTS ----
function computeOrganic(){
  _seed=20260627;
  var nc=nodes.length,scale=Math.max(1,Math.sqrt(nc/6));
  var cx=480*scale,cy=360*scale,rad=280*scale,ry=240*scale;
  var avgH=nodes.reduce(function(s,n){return s+n.h;},0)/nc;
  var minSep=NODE_W+40,minSepY=avgH+40;
  var repK=Math.max(180000,NODE_W*NODE_W*nc*1.5),spring=(NODE_W+avgH)*1.2*scale;
  nodes.forEach(function(n,i){var a=i/nc*Math.PI*2;n.x=cx+Math.cos(a)*rad+(rnd()-.5)*40;n.y=cy+Math.sin(a)*ry+(rnd()-.5)*40;});
  for(var it=0;it<500;it++){var cool=1-it/500;
    for(var i=0;i<nc;i++)for(var k=i+1;k<nc;k++){var a=nodes[i],b=nodes[k];
      var dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||1,d=Math.sqrt(d2),rep=repK/d2;
      a.x+=dx/d*rep*cool;a.y+=dy/d*rep*cool;b.x-=dx/d*rep*cool;b.y-=dy/d*rep*cool;}
    edges.forEach(function(e){var dx=e.t.x-e.s.x,dy=e.t.y-e.s.y,d=Math.sqrt(dx*dx+dy*dy)||1,f=(d-spring)*.012*cool;
      e.s.x+=dx/d*f;e.s.y+=dy/d*f;e.t.x-=dx/d*f;e.t.y-=dy/d*f;});
    nodes.forEach(function(n){n.x+=(cx-n.x)*.002*cool;n.y+=(cy-n.y)*.002*cool;});}
  var m={};nodes.forEach(function(n){m[n.t.id]={x:n.x,y:n.y};});
  resolveOverlaps(m);
  return m;
}
function computeStar(){
  const nc=MODEL.tables.length,scale=Math.max(1,Math.sqrt(nc/10));
  const cx=520*scale,cy=360*scale,m={};
  const facts=MODEL.tables.filter(t=>t.kind==="fact"), dims=MODEL.tables.filter(t=>t.kind==="dim");
  const factAngle={};
  const factR=Math.max(150,facts.length*40)*Math.min(scale,2);
  facts.forEach((f,i)=>{const a=facts.length===1?0:(i/facts.length*Math.PI*2-Math.PI/2);factAngle[f.id]=a;
    const r=facts.length===1?0:factR; m[f.id]={x:cx+Math.cos(a)*r,y:cy+Math.sin(a)*r};});
  const dimAngle={};
  dims.forEach(d=>{const fn=undir[d.id].filter(x=>tableById[x]&&tableById[x].kind==="fact");
    if(fn.length){let sx=0,sy=0;fn.forEach(f=>{sx+=Math.cos(factAngle[f]);sy+=Math.sin(factAngle[f]);});dimAngle[d.id]=Math.atan2(sy,sx);}});
  const angleBuckets={};
  dims.forEach((d,i)=>{
    let a=dimAngle[d.id];
    if(a===undefined){const dn=undir[d.id].filter(x=>dimAngle[x]!==undefined);a=dn.length?dimAngle[dn[0]]:i/dims.length*Math.PI*2;}
    const bucket=Math.round(a*10);(angleBuckets[bucket]=angleBuckets[bucket]||[]).push({d,a});});
  Object.values(angleBuckets).forEach(arr=>{if(arr.length<=1)return;
    const baseA=arr[0].a,spread=Math.min(0.6,0.15*arr.length);
    arr.forEach((item,i)=>{item.a=baseA+(i-(arr.length-1)/2)*spread/arr.length*2;});});
  const dimR=Math.max(380,factR+NODE_W+80)*Math.min(scale,2);
  dims.forEach((d,i)=>{
    const bucket=Math.round((dimAngle[d.id]!==undefined?dimAngle[d.id]:i/dims.length*Math.PI*2)*10);
    const entry=(angleBuckets[bucket]||[]).find(x=>x.d===d);
    const a=entry?entry.a:(dimAngle[d.id]!==undefined?dimAngle[d.id]:i/dims.length*Math.PI*2);
    const onlyDim=undir[d.id].every(x=>!tableById[x]||tableById[x].kind==="dim");
    const r=onlyDim?dimR*1.4:dimR;
    m[d.id]={x:cx+Math.cos(a)*r,y:cy+Math.sin(a)*r};});
  resolveOverlaps(m);
  return m;
}
function resolveOverlaps(m){
  const ids=Object.keys(m);
  const pad=30;
  for(let pass=0;pass<12;pass++){let moved=false;
    for(let i=0;i<ids.length;i++){
      const na=nodeById[ids[i]],ha=na?na.h:80;
      for(let k=i+1;k<ids.length;k++){
        const nb=nodeById[ids[k]],hb=nb?nb.h:80;
        const a=m[ids[i]],b=m[ids[k]];
        const dx=a.x-b.x,dy=a.y-b.y;
        const overX=NODE_W+pad-Math.abs(dx),overY=(ha+hb)/2+pad-Math.abs(dy);
        if(overX>0&&overY>0){
          if(overX<overY){const push=overX/2+4;const sx=dx>=0?1:-1;a.x+=push*sx;b.x-=push*sx;}
          else{const push=overY/2+4;const sy=dy>=0?1:-1;a.y+=push*sy;b.y-=push*sy;}
          moved=true;}}}
    if(!moved)break;}
}
function computeLayered(dir){
  const rank={};MODEL.tables.forEach(t=>rank[t.id]=0);
  for(let i=0;i<MODEL.tables.length;i++)MODEL.joins.forEach(j=>{if(rank[j.to]<rank[j.from]+1)rank[j.to]=rank[j.from]+1;});
  const byRank={};MODEL.tables.forEach(t=>{(byRank[rank[t.id]]=byRank[rank[t.id]]||[]).push(t.id);});
  // Crossing reduction (Sugiyama median heuristic): order each rank so a table
  // sits near the tables it joins to, clustering a fact's dimensions beside it.
  const adj={};MODEL.tables.forEach(t=>adj[t.id]=[]);
  MODEL.joins.forEach(j=>{if(adj[j.from]&&adj[j.to]){adj[j.from].push(j.to);adj[j.to].push(j.from);}});
  const ranks=Object.keys(byRank).map(Number).sort((a,b)=>a-b);
  const order={};ranks.forEach(r=>order[r]=byRank[r].slice());
  const posIn=r=>{const p={};(order[r]||[]).forEach((id,i)=>p[id]=i);return p;};
  const median=a=>{if(!a.length)return -1;a.sort((x,y)=>x-y);const n=a.length,h=n>>1;return n%2?a[h]:(a[h-1]+a[h])/2;};
  for(let pass=0;pass<6;pass++){
    const down=pass%2===0;
    const seq=down?ranks.slice(1):ranks.slice(0,-1).reverse();
    seq.forEach(r=>{const p=posIn(down?r-1:r+1),key={};
      order[r].forEach((id,i)=>{const nb=adj[id].filter(n=>rank[n]===(down?r-1:r+1)).map(n=>p[n]).filter(x=>x>=0);
        key[id]=nb.length?median(nb):i;});
      order[r]=order[r].slice().sort((a,b)=>key[a]-key[b]);});
  }
  const isLR=dir==="lr";
  const avgH=nodes.reduce((s,n)=>s+n.h,0)/nodes.length;
  const colGap=isLR?NODE_W+120:Math.max(avgH+60,180);
  const rowGap=isLR?Math.max(avgH+40,160):NODE_W+60;
  const m={};
  ranks.forEach(r=>{const ids=order[r];const span=(ids.length-1)*rowGap;
    ids.forEach((id,i)=>{const along=r*colGap+120, across=i*rowGap-span/2+360;
      m[id]=isLR?{x:along,y:across}:{x:across,y:along};});});
  resolveOverlaps(m);
  return m;
}
function getLayout(name){
  if(layoutCache[name])return layoutCache[name];
  layoutCache[name]=name==="organic"?computeOrganic():name==="star"?computeStar():computeLayered(name);
  return layoutCache[name];
}

// ---- tween ----
let _tweenId=0;
function tweenTo(targets){
  const myId=++_tweenId;
  nodes.forEach(n=>{const t=targets[n.t.id];if(t){n.x=t.x;n.y=t.y;}});
  renderAll();fit();
}
function setLayout(name){layoutName=name;
  document.querySelectorAll("#layout-seg button").forEach(b=>b.classList.toggle("on",b.dataset.l===name));
  const layered=name==="lr"||name==="tb";
  tOrth.disabled=!layered;$("orth-wrap").style.opacity=layered?1:.4;
  updateSavedBadge();
  tweenTo(hasAll(savedPos[name])?savedPos[name]:getLayout(name));}

// ---- focus / path ----
function tableMatchesFilter(t){
  if(activeFilters.has("all"))return true;
  if(activeFilters.has("fact")&&t.kind==="fact")return true;
  if(activeFilters.has("dim")&&t.kind==="dim")return true;
  if(activeFilters.has("sql_view")&&t.is_sql_view)return true;
  if(activeFilters.has("alias")&&t.alias_of)return true;
  if(activeFilters.has("rls")&&t.rls&&t.rls.length>0)return true;
  if(activeFilters.has("rls_subgraph")&&((t.rls&&t.rls.length>0)||t.in_rls_path))return true;
  return false;
}
function focusGroup(){
  if(!activeFilters.has("all")&&!focusSet.length){
    const k=new Set();MODEL.tables.forEach(t=>{if(tableMatchesFilter(t))k.add(t.id);});return k;}
  if(!focusSet.length)return null;
  const keep=new Set(focusSet);
  if(focusMode==="tree"){
    // double-click: exactly the join subtree (focusSet already is it) — no neighbours.
  }else if(focusMode==="compare"){
    // shift-click: keep the picked tables plus the tables on the path between them.
    for(let i=0;i<focusSet.length-1;i++){shortestPath(focusSet[i],focusSet[i+1]).forEach(n=>keep.add(n));}
  }else{
    // single-click: the table's immediate neighbourhood.
    focusSet.forEach(id=>(undir[id]||[]).forEach(n=>keep.add(n)));
  }
  if(!activeFilters.has("all")){const filtered=new Set();MODEL.tables.forEach(t=>{if(tableMatchesFilter(t))filtered.add(t.id);});
    return new Set([...keep].filter(id=>filtered.has(id)));}
  return keep;
}
// In tree / compare focus, out-of-scope tables are hidden outright rather than dimmed.
// Guard on an active selection so a stale mode never hides filter results.
function hideOutOfFocus(){return focusSet.length>0&&(focusMode==="tree"||focusMode==="compare");}
function shortestPath(a,b){
  const prev={},q=[a],seen=new Set([a]);
  while(q.length){const n=q.shift();if(n===b)break;(undir[n]||[]).forEach(m=>{if(!seen.has(m)){seen.add(m);prev[m]=n;q.push(m);}});}
  if(!seen.has(b))return [];const path=[b];let c=b;while(c!==a){c=prev[c];if(c===undefined)return [];path.unshift(c);}return path;
}
function pathEdges(){
  if(focusSet.length<2)return new Set();
  const set=new Set();
  for(let i=0;i<focusSet.length-1;i++){const p=shortestPath(focusSet[i],focusSet[i+1]);
    for(let k=0;k<p.length-1;k++){MODEL.joins.forEach(j=>{if((j.from===p[k]&&j.to===p[k+1])||(j.from===p[k+1]&&j.to===p[k]))set.add(j.name);});}}
  return set;
}

const NS_el=(tag,attrs,parent)=>{const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e;};
const center=n=>({x:n.x+n.w/2,y:n.y+n.h/2});
function border(n,toward){const c=center(n),dx=toward.x-c.x,dy=toward.y-c.y,hw=n.w/2,hh=n.h/2;
  const s=Math.min(dx===0?1e9:hw/Math.abs(dx),dy===0?1e9:hh/Math.abs(dy));return {x:c.x+dx*s,y:c.y+dy*s};}

function computeLanes(){
  const buckets={};
  edges.forEach(e=>{e.s.h=nodeHeight(e.s.t);e.t.h=nodeHeight(e.t.t);
    const base=layoutName==="lr"?(e.s.x+e.s.w+e.t.x)/2:(e.s.y+e.s.h+e.t.y)/2;
    const key=Math.round(base/6);(buckets[key]=buckets[key]||[]).push(e);});
  Object.values(buckets).forEach(arr=>{
    arr.sort((a,b)=>layoutName==="lr"?(a.s.y-b.s.y):(a.s.x-b.s.x));
    arr.forEach((e,i)=>e.lane=(i-(arr.length-1)/2)*20);});
}
function edgeGeom(e,orth){
  const s=e.s,t=e.t;
  if(orth&&layoutName==="lr"){const sp={x:s.x+s.w,y:s.y+s.h/2},tp={x:t.x,y:t.y+t.h/2},mx=(sp.x+tp.x)/2+(e.lane||0);
    return {sp,tp,sdir:{x:1,y:0},tdir:{x:-1,y:0},d:`M${sp.x},${sp.y} H${mx} V${tp.y} H${tp.x}`,mx,my:(sp.y+tp.y)/2};}
  if(orth&&layoutName==="tb"){const sp={x:s.x+s.w/2,y:s.y+s.h},tp={x:t.x+t.w/2,y:t.y},my=(sp.y+tp.y)/2+(e.lane||0);
    return {sp,tp,sdir:{x:0,y:1},tdir:{x:0,y:-1},d:`M${sp.x},${sp.y} V${my} H${tp.x} V${tp.y}`,mx:(sp.x+tp.x)/2,my};}
  const sp=border(s,center(t)),tp=border(t,center(s)),len=Math.hypot(tp.x-sp.x,tp.y-sp.y)||1;
  const sdir={x:(tp.x-sp.x)/len,y:(tp.y-sp.y)/len};
  return {sp,tp,sdir,tdir:{x:-sdir.x,y:-sdir.y},d:`M${sp.x},${sp.y} L${tp.x},${tp.y}`,mx:(sp.x+tp.x)/2,my:(sp.y+tp.y)/2};
}
function drawCard(g,p,dir,many,color){const perp={x:-dir.y,y:dir.x};
  if(many){const tip={x:p.x+dir.x*15,y:p.y+dir.y*15};[6,0,-6].forEach(o=>NS_el("line",{x1:tip.x,y1:tip.y,x2:p.x+perp.x*o,y2:p.y+perp.y*o,stroke:color,"stroke-width":1.5,"stroke-linecap":"round"},g));}
  else{const c={x:p.x+dir.x*10,y:p.y+dir.y*10};NS_el("line",{x1:c.x+perp.x*6,y1:c.y+perp.y*6,x2:c.x-perp.x*6,y2:c.y-perp.y*6,stroke:color,"stroke-width":1.7,"stroke-linecap":"round"},g);}}
function originBadge(g,x,y,origin){const m=origin==="model";
  NS_el("rect",{x:x-7,y:y-7,width:14,height:14,rx:4,fill:m?"#1E6FA8":"#EDEFF2",stroke:m?"#1E6FA8":"#C8CFD8","stroke-width":1},g);
  NS_el("text",{x,y:y+3.4,"text-anchor":"middle","font-size":9,"font-weight":700,fill:m?"#fff":"#6B7480"},g).textContent=m?"M":"T";}

function renderEdges(){
  gEdges.innerHTML="";
  const showF=tFind.checked,keep=focusGroup(),pe=pathEdges();
  const orth=tOrth.checked&&(layoutName==="lr"||layoutName==="tb");
  const crow=notation==="crow";
  if(orth)computeLanes();
  edges.forEach(e=>{
    e.s.h=nodeHeight(e.s.t);e.t.h=nodeHeight(e.t.t);
    const G=edgeGeom(e,orth);
    const hot=showF&&HOT_EDGES.has(e.j.name);
    const onPath=pe.has(e.j.name);
    const sel=selected&&selected.type==="edge"&&selected.id===e.j.name;
    const ghost=keep&&!(keep.has(e.j.from)&&keep.has(e.j.to));
    const annotated=!!notes[e.j.name];
    let stroke=annotated?"#D97706":"#9AA4B1",sw=annotated?2:1.6,dash="0",mk="url(#arrow)";
    if(hot){stroke="#9AA4B1";sw=2;dash="6 4";mk="url(#arrow)";}
    if(onPath||sel){stroke="#1E6FA8";sw=3;dash="0";mk="url(#arrow-sel)";}
    const g=NS_el("g",{class:"edge-g"+(ghost?(hideOutOfFocus()?" gone":" ghost"):""),style:"cursor:pointer"},gEdges);
    NS_el("path",{class:"edge",fill:"none",d:G.d,stroke,"stroke-width":sw,"stroke-dasharray":dash,"marker-end":crow?"none":mk,"stroke-linejoin":"round"},g);
    NS_el("path",{d:G.d,stroke:"transparent","stroke-width":16,fill:"none"},g);
    if(crow){const card=e.j.card,parts=(card&&card.includes("_TO_"))?card.split("_TO_"):["MANY","ONE"];
      drawCard(g,G.sp,G.sdir,parts[0]==="MANY",stroke);drawCard(g,G.tp,G.tdir,parts[1]==="MANY",stroke);}
    originBadge(g,G.mx,G.my,e.j.origin||"table");
    g.addEventListener("click",ev=>{ev.stopPropagation();selectEdge(e.j.name);});
  });
}

function renderNodes(){
  gNodes.innerHTML="";
  const showF=tFind.checked,keep=focusGroup();
  nodes.forEach(n=>{
    const t=n.t,isFact=t.kind==="fact";n.h=nodeHeight(t);
    const sev=showF?worstSev(t.id):null;
    // Two inherent RLS node states, always shown (like SQL View / Alias):
    //   secured   = a rule is defined ON this table (red)
    //   inRlsPath = this table is referenced in ANOTHER table's rule expression (amber)
    // RLS does not propagate across join edges, so there is no join-inherited state.
    const secured=t.rls&&t.rls.length;
    const inRlsPath=t.in_rls_path&&!secured;
    const inFocus=focusSet.includes(t.id);
    const ghost=keep&&!keep.has(t.id);
    const g=NS_el("g",{class:"node"+(ghost?(hideOutOfFocus()?" gone":" ghost"):""),transform:`translate(${n.x},${n.y})`},gNodes);

    let stroke=isFact?"#1E6FA8":"#C8CFD8",sw=isFact?1.6:1.2;
    if(secured){stroke="#C2382E";sw=2.2;} else if(inRlsPath){stroke="#D97706";sw=2.2;}
    if(sev==="crit"){stroke="#C2382E";sw=2.2;} else if(sev==="warn"){stroke="#B5730A";sw=2;}
    if(inFocus){stroke="#1E6FA8";sw=2.8;}
    let fill=secured?"#FBE9E7":inRlsPath?"#FEF3C7":t.is_sql_view?"#F0FDFA":"#fff";

    NS_el("rect",{x:0,y:0,width:n.w,height:n.h,rx:10,fill,stroke,"stroke-width":sw,style:"filter:drop-shadow(0 2px 5px rgba(20,27,38,.08))"},g);
    const hbg=secured?"#FBE9E7":isFact?"#EAF2F8":"#EEF0F3";
    NS_el("rect",{x:0,y:0,width:n.w,height:HEAD_H,rx:10,fill:hbg},g);
    NS_el("rect",{x:0,y:HEAD_H-10,width:n.w,height:10,fill:hbg},g);
    NS_el("line",{x1:0,y1:HEAD_H,x2:n.w,y2:HEAD_H,stroke:"#E2E6EC","stroke-width":1},g);

    const nh=NS_el("text",{class:"nh",x:12,y:20,fill:"#161B26"},g);nh.textContent=t.id;
    let bx=n.w-10;
    if(secured){const sh=NS_el("text",{x:bx-2,y:20,"text-anchor":"end","font-size":13},g);sh.textContent="🔒";bx-=22;}
    const bw=isFact?30:26;
    NS_el("rect",{x:bx-bw,y:9,width:bw,height:14,rx:4,fill:isFact?"#1E6FA8":"#C8CFD8"},g);
    const bd=NS_el("text",{class:"nbadge",x:bx-bw/2,y:19,"text-anchor":"middle",fill:isFact?"#fff":"#5A626E"},g);bd.textContent=isFact?"FACT":"DIM";
    bx-=bw+4;
    if(t.is_sql_view){const svw=18;NS_el("rect",{x:bx-svw,y:9,width:svw,height:14,rx:4,fill:"#0D9488"},g);
      NS_el("text",{class:"nbadge",x:bx-svw/2,y:19,"text-anchor":"middle",fill:"#fff"},g).textContent="SV";bx-=svw+3;}
    if(t.alias_of){const aw=14;NS_el("rect",{x:bx-aw,y:9,width:aw,height:14,rx:4,fill:"#7C3AED"},g);
      NS_el("text",{class:"nbadge",x:bx-aw/2,y:19,"text-anchor":"middle",fill:"#fff"},g).textContent="A";bx-=aw+3;}
    if(notes[t.id]){const nw=14;NS_el("rect",{x:bx-nw,y:9,width:nw,height:14,rx:4,fill:"#D97706"},g);
      NS_el("text",{class:"nbadge",x:bx-nw/2,y:19.5,"text-anchor":"middle",fill:"#fff","font-size":10},g).textContent="✎";bx-=nw+3;}

    const cols=visibleCols(t);
    cols.forEach((c,i)=>{const y=HEAD_H+i*ROW_H;
      const cn=NS_el("text",{class:"col-name"+(c.key?" col-key":""),x:12,y:y+15,fill:c.key?"#8A93A0":"#2A3140"},g);
      const maxCh=Math.floor((n.w-30)/7);const nm=c.name.length>maxCh?c.name.slice(0,maxCh-1)+"…":c.name;cn.textContent=(c.key?"🔑 ":"")+nm;
      let badge=c.role==="MEASURE"?"#":c.role==="FORMULA"?"ƒ":c.key?"":"·";
      let bc=c.role==="MEASURE"?"#2E8B62":c.role==="FORMULA"?"#1E6FA8":"#9AA4B1";
      if(c.flag&&showF){badge="●";bc=c.flag==="crit"?"#C2382E":c.flag==="warn"?"#B5730A":"#1E6FA8";}
      NS_el("text",{x:n.w-12,y:y+15,"text-anchor":"end","font-size":11,"font-family":"var(--mono)","font-weight":700,fill:bc},g).textContent=badge;});

    enableDrag(g,n);
    g.addEventListener("click",ev=>{ev.stopPropagation();selectTable(t.id,ev.shiftKey||ev.metaKey||ev.ctrlKey);});
    g.addEventListener("dblclick",ev=>{ev.stopPropagation();const tree=joinTree(t.id);focusSet=[...tree];focusMode="tree";selected={type:"table",id:t.id};renderAll();showTable(t.id);});
  });
}
function renderAll(){renderEdges();renderNodes();}

// ---- pan / zoom ----
// MIN_K is the single shared zoom floor: fit(), wheel-zoom and #zoom-out all clamp to
// it, so a fresh fit (which can land below the old hardcoded 0.25) never snap-zooms on
// the first wheel/button press.
const MIN_K=0.12;
const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
let view={x:0,y:0,k:1};
const applyView=()=>{vp.setAttribute("transform",`translate(${view.x},${view.y}) scale(${view.k})`);updateMinimapViewport();};
function screenToWorld(cx,cy){const r=svg.getBoundingClientRect();return {x:(cx-r.left-view.x)/view.k,y:(cy-r.top-view.y)/view.k};}
function nodesBBox(list){
  if(!list||!list.length)return {x0:0,y0:0,x1:1,y1:1};
  let a=1e9,b=1e9,c=-1e9,d=-1e9;
  list.forEach(n=>{n.h=nodeHeight(n.t);a=Math.min(a,n.x);b=Math.min(b,n.y);c=Math.max(c,n.x+n.w);d=Math.max(d,n.y+n.h);});
  return {x0:a,y0:b,x1:c,y1:d};
}
function fitNodes(subset){
  const bb=nodesBBox(subset&&subset.length?subset:nodes);
  const pad=70,r=svg.getBoundingClientRect(),w=bb.x1-bb.x0+pad*2,h=bb.y1-bb.y0+pad*2;
  view.k=clamp(Math.min(r.width/w,r.height/h),MIN_K,1.35);
  view.x=(r.width-(bb.x1+bb.x0)*view.k)/2;view.y=(r.height-(bb.y1+bb.y0)*view.k)/2;applyView();
}
function fit(){fitNodes(nodes);renderMinimap();}
// #zoom-fit / keyboard "0": fit to the focused neighbourhood when something is focused
// (keeps focus alive), otherwise fall back to the old clear-and-fit-everything behaviour.
function fitOrFocus(){
  if(!focusSet.length){focusSet=[];focusMode=null;renderAll();fit();return;}
  const keep=focusGroup(),subset=nodes.filter(n=>keep&&keep.has(n.t.id));
  fitNodes(subset);
}
function centerOn(n){const r=svg.getBoundingClientRect();view.x=r.width/2-(n.x+n.w/2)*view.k;view.y=r.height/2-(n.y+n.h/2)*view.k;applyView();}

let panning=false,panStart=null,panFrom=null,panMoved=0,suppressClick=false;
svg.addEventListener("pointerdown",e=>{suppressClick=false;if(e.target.closest(".node")||e.target.closest(".edge-g"))return;
  panning=true;panMoved=0;panFrom={x:e.clientX,y:e.clientY};
  panStart={x:e.clientX-view.x,y:e.clientY-view.y};svg.classList.add("panning");svg.setPointerCapture(e.pointerId);});
svg.addEventListener("pointermove",e=>{if(!panning)return;
  panMoved=Math.max(panMoved,Math.hypot(e.clientX-panFrom.x,e.clientY-panFrom.y));
  view.x=e.clientX-panStart.x;view.y=e.clientY-panStart.y;applyView();});
svg.addEventListener("pointerup",()=>{panning=false;svg.classList.remove("panning");if(panMoved>4)suppressClick=true;});
svg.addEventListener("pointercancel",()=>{panning=false;svg.classList.remove("panning");});
// A pan-drag ends with a synthetic click; suppressClick (set above once movement passes
// the threshold) eats that one click so a drag never wipes the user's focus/selection.
svg.addEventListener("click",e=>{
  if(suppressClick){suppressClick=false;return;}
  if(!e.target.closest(".node")&&!e.target.closest(".edge-g")){focusSet=[];focusMode=null;selected=null;renderAll();showOverview();}});
svg.addEventListener("wheel",e=>{
  e.preventDefault();
  const r=svg.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  if(e.ctrlKey||e.metaKey){ // trackpad pinch reports ctrlKey:true; ⌘/Ctrl+scroll is explicit zoom
    const wx=(mx-view.x)/view.k,wy=(my-view.y)/view.k,f=e.deltaY<0?1.12:1/1.12;
    view.k=clamp(view.k*f,MIN_K,2.4);view.x=mx-wx*view.k;view.y=my-wy*view.k;applyView();
    return;
  }
  const mult=e.deltaMode===1?16:1; // line-mode wheel notches (deltaMode 1) pan a token amount otherwise
  view.x-=e.deltaX*mult;view.y-=e.deltaY*mult;applyView();
},{passive:false});
$("zoom-in").onclick=()=>{view.k=clamp(view.k*1.18,MIN_K,2.4);applyView();};
$("zoom-out").onclick=()=>{view.k=clamp(view.k/1.18,MIN_K,2.4);applyView();};
$("zoom-fit").onclick=fitOrFocus;

// ---- minimap ----
// Fixed-size overview, bottom-right of the canvas. mmT (scale + world origin) is shared
// by renderMinimap/updateMinimapViewport/minimapToWorld; it stays null until the first
// renderMinimap() call, which updateMinimapViewport() must tolerate (see its guard) since
// the very first applyView() — from the initial loadModel()->fit() — fires before that.
const MM_W=180,MM_H=130,MM_PAD=6;
let mmT=null;
function mmFill(t){ // same kind->fill mapping renderNodes uses: fact vs. dim, sql_view distinct
  if(t.is_sql_view)return "#F0FDFA";
  return t.kind==="fact"?"#EAF2F8":"#EEF0F3";
}
function renderMinimap(){
  const host=$("minimap-nodes");host.innerHTML="";
  const bb=nodesBBox(nodes),w=Math.max(1,bb.x1-bb.x0),h=Math.max(1,bb.y1-bb.y0);
  const scale=Math.min((MM_W-MM_PAD*2)/w,(MM_H-MM_PAD*2)/h);
  mmT={scale,ox:bb.x0,oy:bb.y0};
  nodes.forEach(n=>{
    NS_el("rect",{x:MM_PAD+(n.x-bb.x0)*scale,y:MM_PAD+(n.y-bb.y0)*scale,
      width:Math.max(1,n.w*scale),height:Math.max(1,n.h*scale),fill:mmFill(n.t)},host);
  });
  updateMinimapViewport();
}
function updateMinimapViewport(){
  if(!mmT)return; // init-order guard — see note above
  const r=svg.getBoundingClientRect();
  const x0=(-view.x)/view.k,y0=(-view.y)/view.k,x1=(r.width-view.x)/view.k,y1=(r.height-view.y)/view.k;
  const rv=$("minimap-view");
  rv.setAttribute("x",MM_PAD+(x0-mmT.ox)*mmT.scale);rv.setAttribute("y",MM_PAD+(y0-mmT.oy)*mmT.scale);
  rv.setAttribute("width",Math.max(0,(x1-x0)*mmT.scale));rv.setAttribute("height",Math.max(0,(y1-y0)*mmT.scale));
}
function minimapToWorld(clientX,clientY){
  const r=$("minimap-svg").getBoundingClientRect();
  return {x:mmT.ox+(clientX-r.left-MM_PAD)/mmT.scale,y:mmT.oy+(clientY-r.top-MM_PAD)/mmT.scale};
}
function navigateMinimap(clientX,clientY){
  if(!mmT)return;
  const w=minimapToWorld(clientX,clientY),r=svg.getBoundingClientRect();
  view.x=r.width/2-w.x*view.k;view.y=r.height/2-w.y*view.k;applyView();
}
let mmDragging=false;
const mmSvg=$("minimap-svg");
mmSvg.addEventListener("pointerdown",e=>{e.stopPropagation();mmDragging=true;mmSvg.setPointerCapture(e.pointerId);navigateMinimap(e.clientX,e.clientY);});
mmSvg.addEventListener("pointermove",e=>{if(!mmDragging)return;e.stopPropagation();navigateMinimap(e.clientX,e.clientY);});
mmSvg.addEventListener("pointerup",e=>{mmDragging=false;e.stopPropagation();});
mmSvg.addEventListener("pointercancel",()=>{mmDragging=false;});

function setMinimapCollapsed(collapsed){
  $("minimap").classList.toggle("collapsed",collapsed);
  $("minimap-toggle").textContent=collapsed?"+":"–";
  $("minimap-toggle").title=collapsed?"Show overview":"Hide overview";
}
const MM_LS_KEY="ts-erd-minimap";
$("minimap-toggle").onclick=()=>{
  const next=!$("minimap").classList.contains("collapsed");
  setMinimapCollapsed(next);
  try{localStorage.setItem(MM_LS_KEY,next?"1":"0");}catch(e){}
};
// Share-HTML safety: shareHTML() bakes in whatever .collapsed class is on the DOM at save
// time, so a shared copy could open in a stale state. Sync from *this* viewer's own
// localStorage on every load instead, regardless of the baked class.
setMinimapCollapsed((()=>{try{return localStorage.getItem(MM_LS_KEY)==="1";}catch(e){return false;}})());

function enableDrag(g,n){let dragging=false,off=null,moved=false;
  g.addEventListener("pointerdown",e=>{dragging=true;moved=false;const w=screenToWorld(e.clientX,e.clientY);off={x:w.x-n.x,y:w.y-n.y};g.setPointerCapture(e.pointerId);g.style.cursor="grabbing";e.stopPropagation();});
  g.addEventListener("pointermove",e=>{if(!dragging)return;moved=true;const w=screenToWorld(e.clientX,e.clientY);n.x=w.x-off.x;n.y=w.y-off.y;g.setAttribute("transform",`translate(${n.x},${n.y})`);renderEdges();});
  g.addEventListener("pointerup",()=>{dragging=false;g.style.cursor="grab";if(moved){captureLayout();renderMinimap();}});
  g.addEventListener("pointercancel",()=>{dragging=false;g.style.cursor="grab";});
}

// ---- selection / inspector ----
function selectTable(id,additive){
  if(additive){const i=focusSet.indexOf(id);if(i>=0)focusSet.splice(i,1);else focusSet.push(id);
    focusMode=focusSet.length>1?"compare":"neighbourhood";}
  else {focusSet=[id];focusMode="neighbourhood";}
  selected={type:"table",id};renderAll();
  if(focusSet.length>1)showCompare();else if(focusSet.length===1)showTable(focusSet[0]);else showOverview();
}
function selectEdge(name){selected={type:"edge",id:name};renderAll();showEdge(name);}

const ROLE_TAG={MEASURE:["m","measure"],ATTR:["a","attribute"],FORMULA:["f","formula"]};
const esc=s=>String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function findingCard(x){if(!x)return "";return `<div class="finding ${x.sev}" tabindex="0" data-target="${x.target}">
  <div class="fhead"><span class="sev ${x.sev}">${x.sev==="crit"?"Critical":x.sev==="warn"?"Warning":"Info"}</span><span class="check">${esc(x.check)}</span></div>
  <div class="ftitle">${esc(x.title)}</div><div class="ftarget">${esc(x.where)}</div>
  <div class="fdetail">${esc(x.detail)}</div><div class="frec"><b>Fix.</b> ${esc(x.rec)}</div></div>`;}
function ruleCard(r,ownerId){const refs=rlsRefs(r.expr,ownerId);return `<div class="rule"><div class="rname">🔒 ${esc(r.name)}</div>
  <div class="rscope">${esc(r.scope)}</div><div class="expr">${esc(r.expr)}</div>
  ${refs.length?`<div class="affected">References <b>${refs.map(esc).join(", ")}</b>.</div>`:""}</div>`;}
function wireFindings(){inspector.querySelectorAll(".finding").forEach(c=>{const act=()=>{c.classList.toggle("open");const t=c.dataset.target;if(tableById[t])selectTable(t,false);};
  c.addEventListener("click",act);c.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();act();}});});}

function buildModelSummary(){
  const facts=MODEL.tables.filter(t=>t.kind==="fact"),dims=MODEL.tables.filter(t=>t.kind==="dim");
  const allCols=MODEL.tables.flatMap(t=>t.cols||[]);
  const measures=allCols.filter(c=>c.role==="MEASURE"),attrs=allCols.filter(c=>c.role==="ATTR"&&!c.key);
  const keys=allCols.filter(c=>c.key),formCount=Object.keys(MODEL.formulas).length;
  let h=`<div style="font-size:12px;line-height:1.7;color:#3C4453">`;
  h+=`<div style="display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin-bottom:8px">`;
  h+=`<span style="color:var(--muted)">Tables</span><span><b>${facts.length}</b> fact, <b>${dims.length}</b> dimension</span>`;
  h+=`<span style="color:var(--muted)">Columns</span><span><b>${measures.length}</b> measures, <b>${attrs.length}</b> attributes, <b>${keys.length}</b> join keys</span>`;
  h+=`<span style="color:var(--muted)">Joins</span><span><b>${MODEL.joins.length}</b> joins (depth ${MODEL.joins.reduce((mx,j)=>{let d=0,c=j.to;const seen=new Set();while(c&&!seen.has(c)){seen.add(c);const nxt=MODEL.joins.find(x=>x.from===c);if(nxt){d++;c=nxt.to;}else break;}return Math.max(mx,d);},0)})</span>`;
  if(formCount)h+=`<span style="color:var(--muted)">Formulas</span><span><b>${formCount}</b></span>`;
  if(securedTables.length)h+=`<span style="color:var(--muted)">Security</span><span><b>${securedTables.length}</b> RLS-secured table${securedTables.length>1?"s":""}</span>`;
  h+=`</div>`;
  if(facts.length)h+=`<div style="margin-bottom:4px"><span style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em">Fact tables:</span> ${facts.map(f=>`<span style="font-family:var(--mono);font-weight:500">${esc(f.id)}</span>`).join(", ")}</div>`;
  if(dims.length)h+=`<div><span style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em">Dimensions:</span> ${dims.map(d=>`<span style="font-family:var(--mono);font-weight:500">${esc(d.id)}</span>`).join(", ")}</div>`;
  h+=`</div>`;
  return h;
}
function showOverview(){
  let h=`<h2>${esc(MODEL.model.name)}</h2>`;
  if(MODEL.model.description)h+=`<p class="sub">${esc(MODEL.model.description)}</p>`;
  const corpus=MODEL.model.ai_analysis;
  if(corpus){
    if(corpus.domain){h+=`<details class="inspector-section" open><summary class="section-label">Model domain</summary><p class="sub">${esc(corpus.domain)}</p></details>`;}
    if(corpus.objectives&&corpus.objectives.length){h+=`<details class="inspector-section" open><summary class="section-label">Key objectives</summary><ul style="margin:0 0 14px;padding-left:18px;font-size:11.5px;line-height:1.6;color:#3C4453">`;
      corpus.objectives.forEach(o=>h+=`<li>${esc(o)}</li>`);h+=`</ul></details>`;}
    if(corpus.personas&&corpus.personas.length){h+=`<details class="inspector-section" open><summary class="section-label">Audience</summary><ul style="margin:0 0 14px;padding-left:18px;font-size:11.5px;line-height:1.6;color:#3C4453">`;
      corpus.personas.forEach(p=>h+=`<li>${esc(p)}</li>`);h+=`</ul></details>`;}
    if(corpus.questions&&corpus.questions.length){h+=`<details class="inspector-section"><summary class="section-label">Business questions</summary><ul style="margin:0 0 14px;padding-left:18px;font-size:11.5px;line-height:1.6;color:#3C4453">`;
      corpus.questions.forEach(q=>h+=`<li>${esc(q)}</li>`);h+=`</ul></details>`;}}
  h+=`<details class="inspector-section" open><summary class="section-label">Model structure</summary>${buildModelSummary()}</details>`;
  const ai=MODEL.model.ai_instructions;
  if(ai&&ai.length){
    h+=`<details class="inspector-section"><summary class="section-label">AI instructions (${ai.length})</summary><ul style="margin:0 0 14px;padding-left:18px;font-size:11.5px;line-height:1.6;color:#3C4453">`;
    ai.forEach(inst=>h+=`<li>${esc(inst)}</li>`);h+=`</ul></details>`;}
  h+=`<details class="inspector-section"${MODEL.findings.length?" open":""}><summary class="section-label">Findings (${MODEL.findings.length})</summary>`;
  if(MODEL.findings.length){MODEL.findings.forEach(x=>h+=findingCard(x));}else{h+=`<p class="sub">No findings for this model.</p>`;}
  h+=`</details>`;
  if(securedTables.length){
    h+=`<details class="inspector-section"><summary class="section-label">Row-level security (${securedTables.length})</summary>`;
    MODEL.tables.filter(t=>t.rls&&t.rls.length).forEach(t=>{h+=`<div style="font-size:11.5px;font-weight:600;margin-bottom:6px;font-family:var(--mono)">${esc(t.id)}</div>`+t.rls.map(r=>ruleCard(r,t.id)).join("");});
    h+=`</details>`;}
  inspector.innerHTML=h;wireFindings();inspector.scrollTop=0;
}
function colRow(c){const[cls,label]=ROLE_TAG[c.role]||["a","attribute"];const meta=c.key?"join key":(c.agg?`${label} · ${c.agg}`:label);
  const desc=c.desc?`<div class="c-desc">${esc(c.desc)}</div>`:"";
  const ai=c.ai_context?`<div class="c-desc c-ai"><span class="ai-tag">AI</span>${esc(c.ai_context)}</div>`:"";
  const syn=(c.synonyms&&c.synonyms.length)?`<div class="c-syn">${c.synonyms.map(s=>`<span class="syn">${esc(s)}</span>`).join("")}</div>`:"";
  return `<tr class="${c.key?"c-key":""}"><td class="c-name">${c.flag?`<span class="fdot ${c.flag}"></span>`:""}${esc(c.name)}${desc}${ai}${syn}</td>
    <td class="c-type"><span class="tag ${c.key?"k":cls}">${esc(meta)}</span></td></tr>`;}
// Flat headed group — NOT a nested <details>. The parent "Columns" section is
// already a <details>; nesting a second disclosure inside it renders inconsistently
// across browsers (the inner rows can stay hidden), so column groups are always-open.
function colGroup(label,cols){if(!cols.length)return "";
  return `<div class="col-group"><div class="col-group-h">${label} <span class="grp-count">${cols.length}</span></div><table class="cols">${cols.map(colRow).join("")}</table></div>`;}
function showTable(id){
  const t=tableById[id],conns=MODEL.joins.filter(j=>j.from===id||j.to===id),fs=findingsByTable[id]||[];
  const allCols=t.cols||[];
  const keys=allCols.filter(c=>c.key),measures=allCols.filter(c=>!c.key&&c.role==="MEASURE"),
    formulas=allCols.filter(c=>!c.key&&c.role==="FORMULA"),attrs=allCols.filter(c=>!c.key&&c.role!=="MEASURE"&&c.role!=="FORMULA");
  let h=`<button class="backlink" id="back">← Overview</button><h2>${esc(t.id)}</h2>
    <div style="margin:2px 0 14px;display:flex;gap:6px;flex-wrap:wrap"><span class="pill ${t.kind}">${t.kind==="fact"?"Fact table":"Dimension"}</span>
    ${t.rls&&t.rls.length?'<span class="pill rls">🔒 Secured</span>':""}
    ${t.is_sql_view?'<span class="pill" style="color:#0D9488;background:#F0FDFA;border-color:#99F6E4">SQL View</span>':""}
    ${t.alias_of?`<span class="pill" style="color:#7C3AED;background:#F5F3FF;border-color:#DDD6FE">Alias of ${esc(t.alias_of)}</span>`:""}
    ${t.in_rls_path?'<span class="pill" style="color:#D97706;background:#FFFBEB;border-color:#FDE68A">In RLS path</span>':""}</div>`;
  h+=`<details class="inspector-section" open><summary class="section-label">Columns (${allCols.length})</summary>`;
  h+=colGroup("Join keys",keys);
  h+=colGroup("Measures",measures);
  h+=colGroup("Attributes",attrs);
  h+=colGroup("Formulas",formulas);
  h+=`</details>`;
  const fcols=allCols.filter(c=>c.role==="FORMULA"&&MODEL.formulas[c.name]);
  if(fcols.length){h+=`<details class="inspector-section"><summary class="section-label">Formula expressions (${fcols.length})</summary>`;fcols.forEach(c=>h+=`<div style="font-size:11.5px;font-weight:600;margin:0 0 5px">${esc(c.name)}</div><div class="expr">${esc(MODEL.formulas[c.name])}</div>`);h+=`</details>`;}
  if(t.rls&&t.rls.length){h+=`<details class="inspector-section" open><summary class="section-label">RLS rules</summary>`;t.rls.forEach(r=>h+=ruleCard(r,id));h+=`</details>`;}
  h+=`<details class="inspector-section" open><summary class="section-label">Joins (${conns.length})</summary>`;
  conns.forEach(j=>{const other=j.from===id?j.to:j.from,dir=j.from===id?"→":"←";
    h+=`<div style="font-size:12px;font-family:var(--mono);padding:5px 0;border-bottom:1px solid var(--hair-2);cursor:pointer" data-jump="${esc(j.name)}">${dir} ${esc(other)}</div>`;});
  h+=`</details>`;
  if(fs.length){h+=`<details class="inspector-section" open><summary class="section-label">Findings (${fs.length})</summary>`;fs.forEach(x=>h+=findingCard(x));h+=`</details>`;}
  if(t.is_sql_view&&t.sql_query){h+=`<details class="inspector-section"><summary class="section-label">SQL query</summary><div class="expr">${esc(t.sql_query)}</div></details>`;}
  if(t.alias_of){h+=`<div class="section-label">Alias</div><p class="sub">This model table is an alias of the physical table <b style="font-family:var(--mono)">${esc(t.alias_of)}</b>. The underlying columns and data are shared.</p>`;}
  if(t.in_rls_path){const refs=MODEL.tables.filter(x=>x.rls&&x.rls.length&&x.rls.some(r=>(r.expr||"").includes("["+t.id+"::")));
    h+=`<div class="section-label">In RLS path</div><p class="sub">This table is referenced in RLS expressions on ${refs.length?`<b style="color:var(--rls)">${refs.map(x=>esc(x.id)).join(", ")}</b>`:"other tables"}. Changes to its data affect row-level security filtering.</p>`;}
  h+=notesSection(id);
  h+=`<p class="note">Tip: <b>Shift-click</b> another table to compare and trace the join path between them.</p>`;
  inspector.innerHTML=h;$("back").onclick=()=>{focusSet=[];selected=null;renderAll();showOverview();};
  inspector.querySelectorAll("[data-jump]").forEach(e=>e.onclick=()=>selectEdge(e.dataset.jump));wireFindings();wireNotes(id);inspector.scrollTop=0;
}
function showCompare(){
  let h=`<button class="backlink" id="back">← Overview</button><h2>Comparing ${focusSet.length} tables</h2>
    <p class="sub">Focused tables and their direct neighbours stay vivid; the join path between them is highlighted in blue.</p>
    <div>${focusSet.map(id=>`<span class="chip">${esc(id)} <button data-rm="${esc(id)}" aria-label="remove">×</button></span>`).join("")}</div>`;
  const p=focusSet.length===2?shortestPath(focusSet[0],focusSet[1]):null;
  if(p&&p.length){h+=`<div class="section-label">Join path</div><div style="font-size:12px;font-family:var(--mono);line-height:1.9">${p.map(esc).join(" <span style='color:var(--accent)'>→</span> ")}</div>`;}
  else if(focusSet.length===2){h+=`<p class="sub">No join path connects these two tables.</p>`;}
  inspector.innerHTML=h;$("back").onclick=()=>{focusSet=[];selected=null;renderAll();showOverview();};
  inspector.querySelectorAll("[data-rm]").forEach(b=>b.onclick=()=>selectTable(b.dataset.rm,true));inspector.scrollTop=0;
}
function showEdge(name){const j=MODEL.joins.find(x=>x.name===name);if(!j){showOverview();return;}
  const hot=HOT_EDGES.has(name);
  const cardTxt={MANY_TO_ONE:"Many-to-one · N:1",ONE_TO_MANY:"One-to-many · 1:N",ONE_TO_ONE:"One-to-one · 1:1",MANY_TO_MANY:"Many-to-many · N:N"}[j.card]||j.card;
  const isModel=j.origin==="model";
  let h=`<button class="backlink" id="back">← Overview</button><h2>Join</h2>
    <p class="sub" style="font-family:var(--mono);color:var(--ink)">${esc(j.from)} → ${esc(j.to)}</p>
    <div class="section-label">Definition</div>
    <table class="cols">
      <tr><td>Cardinality</td><td class="c-type"><span class="tag a">${esc(cardTxt)}</span></td></tr>
      <tr><td>Join type</td><td class="c-type"><span class="tag a">${esc((j.type||"").replace("_"," "))}</span></td></tr>
      <tr><td>Defined</td><td class="c-type"><span class="tag ${isModel?"f":"k"}">${isModel?"Model-local":"Table-level"}</span></td></tr>
    </table>
    <p class="sub" style="margin-top:9px">${isModel
      ?`<b style="color:var(--accent)">Model-local</b> — defined inline in this model only. Editing it affects just this model.`
      :`<b>Table-level</b> — defined on the <span style="font-family:var(--mono)">${esc(j.from)}</span> table TML and <b>reusable across every model</b> that uses it. Changing or removing it can ripple to other models.`}</p>
    <div class="section-label">Reference</div><div class="expr">${esc(j.name)}</div>`;
  if(j.on)h+=`<div class="section-label">ON clause</div><div class="expr">${esc(j.on)}</div>`;
  if(hot){const fo=MODEL.findings.find(f=>f.check==="D-FANOUT");
    h+=`<div class="section-label">Flagged</div>`+(fo?findingCard(fo):`<p class="sub">⚠︎ <b>Fan-out risk</b> — <span style="font-family:var(--mono)">${esc(j.to)}</span> is joined by two or more tables, so aggregating a measure across this join can multiply rows. Verify measures on the joined-from side aren't double-counted.</p>`);}
  h+=notesSection(name);
  inspector.innerHTML=h;$("back").onclick=()=>{focusSet=[];selected=null;renderAll();showOverview();};wireNotes(name);inspector.scrollTop=0;
}

function showRlsSubgraph(){
  let h=`<button class="backlink" id="back">← Overview</button><h2>Secured subgraph</h2>
    <p class="sub">Only tables involved in row-level security stay vivid: the tables a rule is defined on, plus any table those rules reference. Everything else is ghosted.</p>
    <div class="section-label">Secured tables (${securedTables.length})</div>`;
  MODEL.tables.filter(t=>t.rls&&t.rls.length).forEach(t=>{
    h+=`<div style="font-size:11.5px;font-weight:600;margin-bottom:6px;font-family:var(--mono);cursor:pointer" data-go="${esc(t.id)}">🔒 ${esc(t.id)}</div>`+t.rls.map(r=>ruleCard(r,t.id)).join("");});
  const inPath=MODEL.tables.filter(t=>t.in_rls_path).map(t=>t.id);
  h+=`<div class="section-label">In RLS path (${inPath.length})</div>
    <p class="sub">${inPath.length?inPath.map(x=>`<span class="chip" data-go="${esc(x)}" style="cursor:pointer">${esc(x)}</span>`).join(""):"None — no rule references another table."}</p>
    <p class="note">Tables referenced inside another table's RLS expression. Changes to their data affect that rule's row filtering.</p>`;
  inspector.innerHTML=h;$("back").onclick=()=>{activeFilters=new Set(["all"]);syncChips();renderAll();showOverview();};
  inspector.querySelectorAll("[data-go]").forEach(e=>e.onclick=()=>selectTable(e.dataset.go,false));inspector.scrollTop=0;
}

// ---- controls wiring ----
document.querySelectorAll("#layout-seg button").forEach(b=>b.onclick=()=>setLayout(b.dataset.l));
document.querySelectorAll("#notation-seg button").forEach(b=>b.onclick=()=>{notation=b.dataset.n;
  document.querySelectorAll("#notation-seg button").forEach(x=>x.classList.toggle("on",x.dataset.n===notation));renderEdges();});
colSel.onchange=()=>{colMode=colSel.value;layoutCache={};nodes.forEach(n=>n.h=nodeHeight(n.t));
  layoutCache.organic=computeOrganic();setLayout(layoutName);};
$("reset-pos").onclick=()=>{delete savedPos[layoutName];persistSaved();
  layoutCache[layoutName]=layoutName==="organic"?computeOrganic():layoutName==="star"?computeStar():computeLayered(layoutName);
  setLayout(layoutName);};
tFind.onchange=renderAll; tOrth.onchange=renderEdges;
function syncChips(){document.querySelectorAll("#filter-chips .fchip").forEach(c=>c.classList.toggle("on",activeFilters.has(c.dataset.f)));}
document.querySelectorAll("#filter-chips .fchip").forEach(c=>c.addEventListener("click",()=>{
  const f=c.dataset.f;
  if(f==="all"){activeFilters=new Set(["all"]);}
  else{activeFilters.delete("all");if(activeFilters.has(f))activeFilters.delete(f);else activeFilters.add(f);
    if(!activeFilters.size)activeFilters.add("all");}
  syncChips();focusSet=[];selected=null;renderAll();
  if(activeFilters.has("rls_subgraph"))showRlsSubgraph();else showOverview();
}));

// ---- share HTML ----
function shareHTML(){
  const doc=document.documentElement.outerHTML;
  const dataEl=document.getElementById("erd-data");
  if(!dataEl)return;
  const posMap={};nodes.forEach(n=>posMap[n.t.id]={x:Math.round(n.x),y:Math.round(n.y)});
  const state=JSON.stringify({positions:posMap,notes:notes});
  const newScript=`window.__ERD_DATA__ = ${dataEl.textContent.split("=").slice(1).join("=").trim().replace(/;$/,"")};
window.ERD_INITIAL_STATE = ${state};`;
  const full=doc.replace(dataEl.outerHTML,`<script id="erd-data">${newScript}<\/script>`);
  const blob=new Blob(["<!doctype html>\n"+full],{type:"text/html"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);
  a.download=(MODEL.model.name||"erd").replace(/[^a-zA-Z0-9_-]/g,"_")+"-erd.html";
  a.click();URL.revokeObjectURL(a.href);
}

// ---- help drawer ----
function toggleHelp(){$("help-drawer").classList.toggle("open");}

$("help-btn").onclick=toggleHelp;
$("help-close").onclick=()=>$("help-drawer").classList.remove("open");
$("share-btn").onclick=shareHTML;
$("clear-notes-btn").onclick=clearAllNotes;

const PAN_STEP=60;
const ARROW_PAN={ArrowLeft:[1,0],ArrowRight:[-1,0],ArrowUp:[0,1],ArrowDown:[0,-1]};
document.addEventListener("keydown",e=>{
  if(e.target.tagName==="INPUT"||e.target.tagName==="TEXTAREA"||e.target.tagName==="SELECT")return;
  if(e.key==="?"||e.key==="/"){e.preventDefault();if(e.key==="/"){$("finder").focus();}else toggleHelp();}
  if(e.key==="Escape")$("help-drawer").classList.remove("open");
  if(ARROW_PAN[e.key]){e.preventDefault();const d=ARROW_PAN[e.key];view.x+=d[0]*PAN_STEP;view.y+=d[1]*PAN_STEP;applyView();}
  else if(e.key==="+"||e.key==="="){e.preventDefault();$("zoom-in").click();}
  else if(e.key==="-"){e.preventDefault();$("zoom-out").click();}
  else if(e.key==="0"){e.preventDefault();$("zoom-fit").click();}
});

// ---- loadModel: rebuild all model-derived state ----
function computeNodeW(){
  let mx=8;
  MODEL.tables.forEach(t=>{if(t.id.length>mx)mx=t.id.length;
    (t.cols||[]).forEach(c=>{if(c.name.length>mx)mx=c.name.length;});});
  return Math.max(200,Math.min(400,mx*7.5+40));
}

function loadModel(m){
  MODEL=m;
  NODE_W=computeNodeW();
  tableById={};MODEL.tables.forEach(t=>tableById[t.id]=t);
  findingsByTable={};MODEL.findings.forEach(f=>(findingsByTable[f.target]=findingsByTable[f.target]||[]).push(f));

  const dimTargets=new Set();
  MODEL.joins.forEach(j=>{const ft=MODEL.tables.find(t=>t.id===j.from),tt=MODEL.tables.find(t=>t.id===j.to);
    if(ft&&ft.kind==="fact"&&tt&&tt.kind==="dim")dimTargets.add(j.to);});
  HOT_EDGES=new Set();
  dimTargets.forEach(did=>{const srcs=MODEL.joins.filter(j=>j.to===did&&MODEL.tables.find(t=>t.id===j.from&&t.kind==="fact"));
    if(srcs.length>1)srcs.forEach(j=>HOT_EDGES.add(j.name));});

  adj={};undir={};
  MODEL.tables.forEach(t=>{adj[t.id]=[];undir[t.id]=[];});
  // Every join endpoint is a real table node — the Python builder drops any join
  // whose target isn't in the model (see parser._build_joins).
  MODEL.joins.forEach(j=>{adj[j.from].push(j.to);undir[j.from].push(j.to);undir[j.to].push(j.from);});

  securedTables=MODEL.tables.filter(t=>t.rls&&t.rls.length).map(t=>t.id);
  const hasRls=securedTables.length>0;
  const hasSqlView=MODEL.tables.some(t=>t.is_sql_view);
  const hasAlias=MODEL.tables.some(t=>t.alias_of);
  const hasFact=MODEL.tables.some(t=>t.kind==="fact");
  const hasDim=MODEL.tables.some(t=>t.kind==="dim");
  document.querySelectorAll("#filter-chips .fchip").forEach(c=>{
    const f=c.dataset.f;if(f==="all")return;
    c.disabled=(f==="rls"||f==="rls_subgraph")?!hasRls:f==="sql_view"?!hasSqlView:f==="alias"?!hasAlias:f==="fact"?!hasFact:f==="dim"?!hasDim:false;
  });

  LS_KEY="ts-erd-layout:"+MODEL.model.name;
  NOTES_KEY="ts-erd-notes:"+MODEL.model.name;
  savedPos=loadSaved();
  notes=loadNotes();

  const initState=window.ERD_INITIAL_STATE||null;
  if(initState){
    if(initState.notes){Object.keys(initState.notes).forEach(k=>{if(!notes[k])notes[k]=initState.notes[k];});persistNotes();}
    if(initState.positions&&!hasAll(savedPos.organic)){savedPos.organic=initState.positions;persistSaved();}
  }

  _seed=20260627;
  nodes=MODEL.tables.map((t,i)=>{const a=i/MODEL.tables.length*Math.PI*2;
    return {t,w:NODE_W,h:nodeHeight(t),x:480+Math.cos(a)*240+(rnd()-.5)*40,y:340+Math.sin(a)*200+(rnd()-.5)*40};});
  nodeById={};nodes.forEach(n=>nodeById[n.t.id]=n);
  edges=MODEL.joins.map(j=>({j,s:nodeById[j.from],t:nodeById[j.to]}));

  layoutCache={organic:computeOrganic()};
  focusSet=[];selected=null;activeFilters=new Set(["all"]);
  syncChips();

  const dl=$("tablelist");dl.innerHTML="";
  MODEL.tables.forEach(t=>{const o=document.createElement("option");o.value=t.id;dl.appendChild(o);});
  $("finder").value="";

  document.querySelector(".brand h1").textContent=MODEL.model.name;
  $("s-tables").textContent=MODEL.tables.length;$("s-joins").textContent=MODEL.joins.length;
  $("s-crit").textContent=MODEL.findings.filter(f=>f.sev==="crit").length;
  $("s-warn").textContent=MODEL.findings.filter(f=>f.sev==="warn").length;
  $("s-rls").textContent=securedTables.length;

  const init0=hasAll(savedPos.organic)?savedPos.organic:layoutCache.organic;
  nodes.forEach(n=>{n.x=init0[n.t.id].x;n.y=init0[n.t.id].y;});
  updateSavedBadge();renderAll();fit();showOverview();
}

$("finder").addEventListener("change",e=>{const id=e.target.value.trim();if(tableById[id]){selectTable(id,false);view.k=Math.max(view.k,0.9);centerOn(nodeById[id]);e.target.value="";}});

// ---- model switcher ----
function buildSwitcher(){
  const host=document.querySelector(".brand");
  if(ERD.models.length<2||document.getElementById("model-switch"))return;
  const sel=document.createElement("select");
  sel.id="model-switch";
  ERD.models.forEach((m,i)=>{
    const o=document.createElement("option");
    o.value=String(i);o.textContent=m.model.name;sel.appendChild(o);
  });
  sel.onchange=()=>loadModel(ERD.models[+sel.value]);
  host.appendChild(sel);
}

// ---- entry point ----
buildSwitcher();
loadModel(MODEL);
