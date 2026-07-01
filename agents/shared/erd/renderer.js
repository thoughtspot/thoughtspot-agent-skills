"use strict";
const ERD = window.__ERD_DATA__ || {models: [], index: [], dropped: []};
let MODEL = ERD.models[0] || {model:{name:"(no model)",guid:"",description:""},tables:[],joins:[],formulas:{},findings:[]};

const SEV_RANK={crit:3,warn:2,info:1};
let tableById={}, findingsByTable={}, HOT_EDGES=new Set();
let adj={}, radj={}, undir={};
let securedTables=[], rlsAffected=new Set();
let LS_KEY="", savedPos={};
let nodes=[], nodeById={}, edges=[];
let layoutCache={};

const NS="http://www.w3.org/2000/svg";
const $=id=>document.getElementById(id);
const svg=$("svg"),vp=$("viewport"),gEdges=$("edges"),gNodes=$("nodes"),inspector=$("inspector");
const tFind=$("findings-toggle"),tRls=$("rls-toggle"),colSel=$("col-mode");
const tOrth=$("orth-toggle"),tRlsOnly=$("rlsonly-toggle");
let rlsOnly=false;

const reduce=matchMedia("(prefers-reduced-motion:reduce)").matches;
const ROW_H=20,HEAD_H=30,PAD=10,NODE_W=200;
let colMode="all", layoutName="organic", notation="arrow";
let focusSet=[];
let selected=null;

function worstSev(id){let w=null;(findingsByTable[id]||[]).forEach(f=>{if(!w||SEV_RANK[f.sev]>SEV_RANK[w])w=f.sev;});return w;}
function ancestors(id){const seen=new Set(),stack=[id];while(stack.length){const n=stack.pop();radj[n].forEach(p=>{if(!seen.has(p)){seen.add(p);stack.push(p);}});}return seen;}

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
const hasAll=m=>m&&MODEL.tables.every(t=>m[t.id]);
function captureLayout(){const m={};nodes.forEach(n=>m[n.t.id]={x:Math.round(n.x),y:Math.round(n.y)});savedPos[layoutName]=m;persistSaved();updateSavedBadge();}
function updateSavedBadge(){$("saved-badge").classList.toggle("on",hasAll(savedPos[layoutName]));}

// ---- LAYOUTS ----
function computeOrganic(){
  _seed=20260627;
  nodes.forEach(function(n,i){var a=i/nodes.length*Math.PI*2;n.x=480+Math.cos(a)*240+(rnd()-.5)*40;n.y=340+Math.sin(a)*200+(rnd()-.5)*40;});
  for(var it=0;it<420;it++){var cool=1-it/420;
    for(var i=0;i<nodes.length;i++)for(var k=i+1;k<nodes.length;k++){var a=nodes[i],b=nodes[k];
      var dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||1,d=Math.sqrt(d2),rep=95000/d2;
      a.x+=dx/d*rep*cool;a.y+=dy/d*rep*cool;b.x-=dx/d*rep*cool;b.y-=dy/d*rep*cool;}
    edges.forEach(function(e){var dx=e.t.x-e.s.x,dy=e.t.y-e.s.y,d=Math.sqrt(dx*dx+dy*dy)||1,f=(d-250)*.015*cool;
      e.s.x+=dx/d*f;e.s.y+=dy/d*f;e.t.x-=dx/d*f;e.t.y-=dy/d*f;});
    nodes.forEach(function(n){n.x+=(480-n.x)*.004*cool;n.y+=(340-n.y)*.004*cool;});}
  var m={};nodes.forEach(function(n){m[n.t.id]={x:n.x,y:n.y};});return m;
}
function computeStar(){
  const cx=520,cy=360,m={};
  const facts=MODEL.tables.filter(t=>t.kind==="fact"), dims=MODEL.tables.filter(t=>t.kind==="dim");
  const factAngle={};
  facts.forEach((f,i)=>{const a=facts.length===1?0:(i/facts.length*Math.PI*2-Math.PI/2);factAngle[f.id]=a;
    const r=facts.length===1?0:150; m[f.id]={x:cx+Math.cos(a)*r,y:cy+Math.sin(a)*r};});
  const dimAngle={};
  dims.forEach(d=>{const fn=undir[d.id].filter(x=>tableById[x].kind==="fact");
    if(fn.length){let sx=0,sy=0;fn.forEach(f=>{sx+=Math.cos(factAngle[f]);sy+=Math.sin(factAngle[f]);});dimAngle[d.id]=Math.atan2(sy,sx);}});
  dims.forEach((d,i)=>{
    let a=dimAngle[d.id];
    if(a===undefined){const dn=undir[d.id].filter(x=>dimAngle[x]!==undefined);a=dn.length?dimAngle[dn[0]]:i/dims.length*Math.PI*2;}
    const onlyDim=undir[d.id].every(x=>tableById[x].kind==="dim");
    const r=onlyDim?560:380; const jitter=(i%2?1:-1)*0.10;
    m[d.id]={x:cx+Math.cos(a+jitter)*r,y:cy+Math.sin(a+jitter)*r};});
  return m;
}
function computeLayered(dir){
  const rank={};MODEL.tables.forEach(t=>rank[t.id]=0);
  for(let i=0;i<MODEL.tables.length;i++)MODEL.joins.forEach(j=>{if(rank[j.to]<rank[j.from]+1)rank[j.to]=rank[j.from]+1;});
  const byRank={};MODEL.tables.forEach(t=>{(byRank[rank[t.id]]=byRank[rank[t.id]]||[]).push(t.id);});
  const colGap=300,rowGap=140,m={};
  Object.keys(byRank).forEach(r=>{const ids=byRank[r];const span=(ids.length-1)*rowGap;
    ids.forEach((id,i)=>{const along=r*colGap+120, across=i*rowGap-span/2+360;
      m[id]=dir==="lr"?{x:along,y:across}:{x:across,y:along};});});
  return m;
}
function getLayout(name){
  if(layoutCache[name])return layoutCache[name];
  layoutCache[name]=name==="star"?computeStar():computeLayered(name);
  return layoutCache[name];
}

// ---- tween ----
function tweenTo(targets){
  if(reduce){nodes.forEach(n=>{n.x=targets[n.t.id].x;n.y=targets[n.t.id].y;});renderAll();fit();return;}
  const from=nodes.map(n=>({x:n.x,y:n.y}));let f=0;const F=26;
  (function step(){f++;const e=f/F,k=e<.5?2*e*e:1-Math.pow(-2*e+2,2)/2;
    nodes.forEach((n,i)=>{n.x=from[i].x+(targets[n.t.id].x-from[i].x)*k;n.y=from[i].y+(targets[n.t.id].y-from[i].y)*k;});
    renderNodes();renderEdges();
    if(f<F)requestAnimationFrame(step);else fit();})();
}
function setLayout(name){layoutName=name;
  document.querySelectorAll("#layout-seg button").forEach(b=>b.classList.toggle("on",b.dataset.l===name));
  const layered=name==="lr"||name==="tb";
  tOrth.disabled=!layered;$("orth-wrap").style.opacity=layered?1:.4;
  updateSavedBadge();
  tweenTo(hasAll(savedPos[name])?savedPos[name]:getLayout(name));}

// ---- focus / path ----
function focusGroup(){
  if(rlsOnly){const k=new Set(securedTables);rlsAffected.forEach(x=>k.add(x));return k;}
  if(!focusSet.length)return null;
  const keep=new Set(focusSet);
  focusSet.forEach(id=>(undir[id]||[]).forEach(n=>keep.add(n)));
  return keep;
}
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
  const showF=tFind.checked,showR=tRls.checked||rlsOnly,keep=focusGroup(),pe=pathEdges();
  const orth=tOrth.checked&&(layoutName==="lr"||layoutName==="tb");
  const crow=notation==="crow";
  if(orth)computeLanes();
  edges.forEach(e=>{
    e.s.h=nodeHeight(e.s.t);e.t.h=nodeHeight(e.t.t);
    const G=edgeGeom(e,orth);
    const hot=showF&&HOT_EDGES.has(e.j.name);
    const rlsEdge=showR&&securedTables.includes(e.j.to);
    const onPath=pe.has(e.j.name);
    const sel=selected&&selected.type==="edge"&&selected.id===e.j.name;
    const ghost=keep&&!(keep.has(e.j.from)&&keep.has(e.j.to));
    let stroke="#9AA4B1",sw=1.6,dash="0",mk="url(#arrow)";
    if(rlsEdge){stroke="#6B4FB8";sw=2.1;dash="5 3";mk="url(#arrow-rls)";}
    if(hot){stroke="#C2382E";sw=2.4;dash="6 4";mk="url(#arrow-hot)";}
    if(onPath||sel){stroke="#1E6FA8";sw=3;dash="0";mk="url(#arrow-sel)";}
    const g=NS_el("g",{class:"edge-g"+(ghost?" ghost":""),style:"cursor:pointer"},gEdges);
    NS_el("path",{class:"edge",fill:"none",d:G.d,stroke,"stroke-width":sw,"stroke-dasharray":dash,"marker-end":crow?"none":mk,"stroke-linejoin":"round"},g);
    NS_el("path",{d:G.d,stroke:"transparent","stroke-width":16,fill:"none"},g);
    if(crow){const[sc,tc]=(e.j.card||"MANY_TO_ONE").split("_TO_");
      drawCard(g,G.sp,G.sdir,sc==="MANY",stroke);drawCard(g,G.tp,G.tdir,tc==="MANY",stroke);}
    if(rlsEdge)NS_el("text",{x:G.mx,y:G.my+4,"text-anchor":"middle","font-size":12},g).textContent="🔒";
    else originBadge(g,G.mx,G.my,e.j.origin||"table");
    g.addEventListener("click",ev=>{ev.stopPropagation();selectEdge(e.j.name);});
  });
}

function renderNodes(){
  gNodes.innerHTML="";
  const showF=tFind.checked,showR=tRls.checked||rlsOnly,keep=focusGroup();
  nodes.forEach(n=>{
    const t=n.t,isFact=t.kind==="fact";n.h=nodeHeight(t);
    const sev=showF?worstSev(t.id):null;
    const secured=showR&&t.rls,affected=showR&&!t.rls&&rlsAffected.has(t.id);
    const inFocus=focusSet.includes(t.id);
    const ghost=keep&&!keep.has(t.id);
    const g=NS_el("g",{class:"node"+(ghost?" ghost":""),transform:`translate(${n.x},${n.y})`},gNodes);

    let stroke=isFact?"#1E6FA8":"#C8CFD8",sw=isFact?1.6:1.2;
    if(secured){stroke="#6B4FB8";sw=2.2;} else if(affected){stroke="#A88FD8";sw=1.6;}
    if(sev==="crit"){stroke="#C2382E";sw=2.2;} else if(sev==="warn"){stroke="#B5730A";sw=2;}
    if(inFocus){stroke="#1E6FA8";sw=2.8;}
    let fill=secured?"#FBFAFE":affected?"#FCFBFE":"#fff";

    NS_el("rect",{x:0,y:0,width:n.w,height:n.h,rx:10,fill,stroke,"stroke-width":sw,style:"filter:drop-shadow(0 2px 5px rgba(20,27,38,.08))"},g);
    const hbg=secured?"#F0ECF9":isFact?"#EAF2F8":"#EEF0F3";
    NS_el("rect",{x:0,y:0,width:n.w,height:HEAD_H,rx:10,fill:hbg},g);
    NS_el("rect",{x:0,y:HEAD_H-10,width:n.w,height:10,fill:hbg},g);
    NS_el("line",{x1:0,y1:HEAD_H,x2:n.w,y2:HEAD_H,stroke:"#E2E6EC","stroke-width":1},g);

    const nh=NS_el("text",{class:"nh",x:12,y:20,fill:"#161B26"},g);nh.textContent=t.id;
    let bx=n.w-10;
    if(secured){const sh=NS_el("text",{x:bx-2,y:20,"text-anchor":"end","font-size":13},g);sh.textContent="🔒";bx-=22;}
    const bw=isFact?30:26;
    NS_el("rect",{x:bx-bw,y:9,width:bw,height:14,rx:4,fill:isFact?"#1E6FA8":"#C8CFD8"},g);
    const bd=NS_el("text",{class:"nbadge",x:bx-bw/2,y:19,"text-anchor":"middle",fill:isFact?"#fff":"#5A626E"},g);bd.textContent=isFact?"FACT":"DIM";

    const cols=visibleCols(t);
    cols.forEach((c,i)=>{const y=HEAD_H+i*ROW_H;
      const cn=NS_el("text",{class:"col-name"+(c.key?" col-key":""),x:12,y:y+15,fill:c.key?"#8A93A0":"#2A3140"},g);
      const nm=c.name.length>22?c.name.slice(0,21)+"…":c.name;cn.textContent=(c.key?"🔑 ":"")+nm;
      let badge=c.role==="MEASURE"?"#":c.role==="FORMULA"?"ƒ":c.key?"":"·";
      let bc=c.role==="MEASURE"?"#2E8B62":c.role==="FORMULA"?"#1E6FA8":"#9AA4B1";
      if(c.flag&&showF){badge="●";bc=c.flag==="crit"?"#C2382E":c.flag==="warn"?"#B5730A":"#1E6FA8";}
      NS_el("text",{x:n.w-12,y:y+15,"text-anchor":"end","font-size":11,"font-family":"var(--mono)","font-weight":700,fill:bc},g).textContent=badge;});

    enableDrag(g,n);
    g.addEventListener("click",ev=>{ev.stopPropagation();selectTable(t.id,ev.shiftKey||ev.metaKey||ev.ctrlKey);});
  });
}
function renderAll(){renderEdges();renderNodes();}

// ---- pan / zoom ----
let view={x:0,y:0,k:1};
const applyView=()=>vp.setAttribute("transform",`translate(${view.x},${view.y}) scale(${view.k})`);
function screenToWorld(cx,cy){const r=svg.getBoundingClientRect();return {x:(cx-r.left-view.x)/view.k,y:(cy-r.top-view.y)/view.k};}
function fit(){let a=1e9,b=1e9,c=-1e9,d=-1e9;nodes.forEach(n=>{n.h=nodeHeight(n.t);a=Math.min(a,n.x);b=Math.min(b,n.y);c=Math.max(c,n.x+n.w);d=Math.max(d,n.y+n.h);});
  const pad=70,r=svg.getBoundingClientRect(),w=c-a+pad*2,h=d-b+pad*2;
  view.k=Math.min(r.width/w,r.height/h,1.35);view.x=(r.width-(c+a)*view.k)/2;view.y=(r.height-(d+b)*view.k)/2;applyView();}
function centerOn(n){const r=svg.getBoundingClientRect();view.x=r.width/2-(n.x+n.w/2)*view.k;view.y=r.height/2-(n.y+n.h/2)*view.k;applyView();}

let panning=false,panStart=null;
svg.addEventListener("pointerdown",e=>{if(e.target.closest(".node")||e.target.closest(".edge-g"))return;
  panning=true;panStart={x:e.clientX-view.x,y:e.clientY-view.y};svg.classList.add("panning");svg.setPointerCapture(e.pointerId);});
svg.addEventListener("pointermove",e=>{if(!panning)return;view.x=e.clientX-panStart.x;view.y=e.clientY-panStart.y;applyView();});
svg.addEventListener("pointerup",()=>{panning=false;svg.classList.remove("panning");});
svg.addEventListener("pointercancel",()=>{panning=false;svg.classList.remove("panning");});
svg.addEventListener("click",e=>{if(!e.target.closest(".node")&&!e.target.closest(".edge-g")){focusSet=[];selected=null;renderAll();showOverview();}});
svg.addEventListener("wheel",e=>{e.preventDefault();const r=svg.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
  const wx=(mx-view.x)/view.k,wy=(my-view.y)/view.k,f=e.deltaY<0?1.12:1/1.12;
  view.k=Math.max(.25,Math.min(2.4,view.k*f));view.x=mx-wx*view.k;view.y=my-wy*view.k;applyView();},{passive:false});
$("zoom-in").onclick=()=>{view.k=Math.min(2.4,view.k*1.18);applyView();};
$("zoom-out").onclick=()=>{view.k=Math.max(.25,view.k/1.18);applyView();};
$("zoom-fit").onclick=()=>{focusSet=[];renderAll();fit();};

function enableDrag(g,n){let dragging=false,off=null,moved=false;
  g.addEventListener("pointerdown",e=>{dragging=true;moved=false;const w=screenToWorld(e.clientX,e.clientY);off={x:w.x-n.x,y:w.y-n.y};g.setPointerCapture(e.pointerId);g.style.cursor="grabbing";e.stopPropagation();});
  g.addEventListener("pointermove",e=>{if(!dragging)return;moved=true;const w=screenToWorld(e.clientX,e.clientY);n.x=w.x-off.x;n.y=w.y-off.y;g.setAttribute("transform",`translate(${n.x},${n.y})`);renderEdges();});
  g.addEventListener("pointerup",()=>{dragging=false;g.style.cursor="grab";if(moved)captureLayout();});
  g.addEventListener("pointercancel",()=>{dragging=false;g.style.cursor="grab";});
}

// ---- selection / inspector ----
function selectTable(id,additive){
  if(additive){const i=focusSet.indexOf(id);if(i>=0)focusSet.splice(i,1);else focusSet.push(id);}
  else focusSet=[id];
  selected={type:"table",id};renderAll();
  if(focusSet.length>1)showCompare();else if(focusSet.length===1)showTable(focusSet[0]);else showOverview();
}
function selectEdge(name){selected={type:"edge",id:name};renderAll();showEdge(name);}

const ROLE_TAG={MEASURE:["m","measure"],ATTR:["a","attribute"],FORMULA:["f","formula"]};
const esc=s=>String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function findingCard(x){return `<div class="finding ${x.sev}" tabindex="0" data-target="${x.target}">
  <div class="fhead"><span class="sev ${x.sev}">${x.sev==="crit"?"Critical":x.sev==="warn"?"Warning":"Info"}</span><span class="check">${esc(x.check)}</span></div>
  <div class="ftitle">${esc(x.title)}</div><div class="ftarget">${esc(x.where)}</div>
  <div class="fdetail">${esc(x.detail)}</div><div class="frec"><b>Fix.</b> ${esc(x.rec)}</div></div>`;}
function ruleCard(r,affectedList){return `<div class="rule"><div class="rname">🔒 ${esc(r.name)}</div>
  <div class="rscope">${esc(r.scope)}</div><div class="expr">${esc(r.expr)}</div>
  ${affectedList?`<div class="affected">Propagates through joins to <b>${affectedList.map(esc).join(", ")}</b>.</div>`:""}</div>`;}
function wireFindings(){inspector.querySelectorAll(".finding").forEach(c=>{const act=()=>{c.classList.toggle("open");const t=c.dataset.target;if(tableById[t])selectTable(t,false);};
  c.addEventListener("click",act);c.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();act();}});});}

function showOverview(){
  let h=`<h2>${esc(MODEL.model.name)}</h2><p class="sub">${esc(MODEL.model.description)}</p>
    <div class="section-label">Findings (${MODEL.findings.length})</div>`;
  MODEL.findings.forEach(x=>h+=findingCard(x));
  h+=`<div class="section-label">Row-level security (${securedTables.length})</div>`;
  MODEL.tables.filter(t=>t.rls&&t.rls.length).forEach(t=>{const aff=[...ancestors(t.id)];h+=`<div style="font-size:11.5px;font-weight:600;margin-bottom:6px;font-family:var(--mono)">${esc(t.id)}</div>`+t.rls.map(r=>ruleCard(r,aff)).join("");});
  h+=`<div class="section-label">Reading the joins</div>
    <p class="sub">Each join carries a midpoint badge: <b style="background:#1E6FA8;color:#fff;border-radius:3px;padding:1px 5px;font-family:var(--mono)">M</b> = model-local (defined in this model only), <b style="background:#EDEFF2;color:#6B7480;border-radius:3px;padding:1px 5px;font-family:var(--mono)">T</b> = table-level (reusable, can ripple to other models). Switch <b>Notation</b> to <b>Crow’s foot</b> to read cardinality instead of TS-style arrows. Click any join for its type, cardinality and definition.</p>`;
  inspector.innerHTML=h;wireFindings();inspector.scrollTop=0;
}
function showTable(id){
  const t=tableById[id],conns=MODEL.joins.filter(j=>j.from===id||j.to===id),fs=findingsByTable[id]||[];
  let h=`<button class="backlink" id="back">← Overview</button><h2>${esc(t.id)}</h2>
    <div style="margin:2px 0 14px;display:flex;gap:6px;flex-wrap:wrap"><span class="pill ${t.kind}">${t.kind==="fact"?"Fact table":"Dimension"}</span>
    ${t.rls&&t.rls.length?'<span class="pill rls">🔒 Secured</span>':rlsAffected.has(id)?'<span class="pill rls">RLS inherited</span>':""}</div>
    <div class="section-label">Columns (${(t.cols||[]).length})</div><table class="cols">`;
  (t.cols||[]).forEach(c=>{const[cls,label]=ROLE_TAG[c.role]||["a","attribute"];const meta=c.key?"join key":(c.agg?`${label} · ${c.agg}`:label);
    h+=`<tr class="${c.key?"c-key":""}"><td class="c-name">${c.flag?`<span class="fdot ${c.flag}"></span>`:""}${esc(c.name)}</td>
      <td class="c-type"><span class="tag ${c.key?"k":cls}">${esc(meta)}</span></td></tr>`;});
  h+=`</table>`;
  const fcols=(t.cols||[]).filter(c=>c.role==="FORMULA"&&MODEL.formulas[c.name]);
  if(fcols.length){h+=`<div class="section-label">Formulas</div>`;fcols.forEach(c=>h+=`<div style="font-size:11.5px;font-weight:600;margin:0 0 5px">${esc(c.name)}</div><div class="expr">${esc(MODEL.formulas[c.name])}</div>`);}
  if(t.rls&&t.rls.length){h+=`<div class="section-label">RLS rules</div>`;t.rls.forEach(r=>h+=ruleCard(r,[...ancestors(id)]));}
  else if(rlsAffected.has(id)){const src=securedTables.filter(s=>ancestors(s).has(id));
    h+=`<div class="section-label">Inherited RLS</div><p class="sub">Queries on this table are constrained by RLS on <b style="color:var(--rls)">${src.map(esc).join(", ")}</b> via joins.</p>`;}
  h+=`<div class="section-label">Joins (${conns.length})</div>`;
  conns.forEach(j=>{const other=j.from===id?j.to:j.from,dir=j.from===id?"→":"←";
    h+=`<div style="font-size:12px;font-family:var(--mono);padding:5px 0;border-bottom:1px solid var(--hair-2);cursor:pointer" data-jump="${esc(j.name)}">${dir} ${esc(other)}</div>`;});
  if(fs.length){h+=`<div class="section-label">Findings (${fs.length})</div>`;fs.forEach(x=>h+=findingCard(x));}
  h+=`<p class="note">Tip: <b>Shift-click</b> another table to compare and trace the join path between them.</p>`;
  inspector.innerHTML=h;$("back").onclick=()=>{focusSet=[];selected=null;renderAll();showOverview();};
  inspector.querySelectorAll("[data-jump]").forEach(e=>e.onclick=()=>selectEdge(e.dataset.jump));wireFindings();inspector.scrollTop=0;
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
function showEdge(name){const j=MODEL.joins.find(x=>x.name===name),hot=HOT_EDGES.has(name),secured=securedTables.includes(j.to);
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
  if(hot)h+=`<div class="section-label">Flagged</div>`+findingCard(MODEL.findings.find(f=>f.check==="D-FANOUT"));
  if(secured)h+=`<div class="section-label">Security</div><p class="sub">Target <b style="color:var(--rls)">${esc(j.to)}</b> has RLS — this join propagates the row filter to <b>${esc(j.from)}</b>.</p>`;
  inspector.innerHTML=h;$("back").onclick=()=>{focusSet=[];selected=null;renderAll();showOverview();};inspector.scrollTop=0;
}

function showRlsSubgraph(){
  let h=`<button class="backlink" id="back">← Overview</button><h2>Secured subgraph</h2>
    <p class="sub">Only tables touched by row-level security stay vivid: the secured tables plus every fact that inherits their row filter through joins. Everything else is ghosted.</p>
    <div class="section-label">Secured tables (${securedTables.length})</div>`;
  MODEL.tables.filter(t=>t.rls&&t.rls.length).forEach(t=>{const aff=[...ancestors(t.id)];
    h+=`<div style="font-size:11.5px;font-weight:600;margin-bottom:6px;font-family:var(--mono);cursor:pointer" data-go="${esc(t.id)}">🔒 ${esc(t.id)}</div>`+t.rls.map(r=>ruleCard(r,aff)).join("");});
  const inh=[...rlsAffected];
  h+=`<div class="section-label">Inherits RLS (${inh.length})</div>
    <p class="sub">${inh.length?inh.map(x=>`<span class="chip">${esc(x)}</span>`).join(""):"None."}</p>
    <p class="note">Turn this off to return to the full model. Use it to answer “if I secure this dimension, what else gets filtered?” at a glance.</p>`;
  inspector.innerHTML=h;$("back").onclick=()=>{tRlsOnly.checked=false;rlsOnly=false;renderAll();showOverview();};
  inspector.querySelectorAll("[data-go]").forEach(e=>e.onclick=()=>selectTable(e.dataset.go,false));inspector.scrollTop=0;
}

// ---- controls wiring ----
document.querySelectorAll("#layout-seg button").forEach(b=>b.onclick=()=>setLayout(b.dataset.l));
document.querySelectorAll("#notation-seg button").forEach(b=>b.onclick=()=>{notation=b.dataset.n;
  document.querySelectorAll("#notation-seg button").forEach(x=>x.classList.toggle("on",x.dataset.n===notation));renderEdges();});
colSel.onchange=()=>{colMode=colSel.value;renderAll();fit();};
$("reset-pos").onclick=()=>{delete savedPos[layoutName];persistSaved();
  layoutCache[layoutName]=layoutName==="organic"?computeOrganic():layoutName==="star"?computeStar():computeLayered(layoutName);
  setLayout(layoutName);};
tFind.onchange=renderAll; tRls.onchange=renderAll; tOrth.onchange=renderEdges;
tRlsOnly.onchange=()=>{rlsOnly=tRlsOnly.checked;if(rlsOnly){focusSet=[];selected=null;}renderAll();if(rlsOnly)showRlsSubgraph();else showOverview();};

// ---- loadModel: rebuild all model-derived state ----
function loadModel(m){
  MODEL=m;
  tableById={};MODEL.tables.forEach(t=>tableById[t.id]=t);
  findingsByTable={};MODEL.findings.forEach(f=>(findingsByTable[f.target]=findingsByTable[f.target]||[]).push(f));

  const dimTargets=new Set();
  MODEL.joins.forEach(j=>{const ft=MODEL.tables.find(t=>t.id===j.from),tt=MODEL.tables.find(t=>t.id===j.to);
    if(ft&&ft.kind==="fact"&&tt&&tt.kind==="dim")dimTargets.add(j.to);});
  HOT_EDGES=new Set();
  dimTargets.forEach(did=>{const srcs=MODEL.joins.filter(j=>j.to===did&&MODEL.tables.find(t=>t.id===j.from&&t.kind==="fact"));
    if(srcs.length>1)srcs.forEach(j=>HOT_EDGES.add(j.name));});

  adj={};radj={};undir={};
  MODEL.tables.forEach(t=>{adj[t.id]=[];radj[t.id]=[];undir[t.id]=[];});
  MODEL.joins.forEach(j=>{adj[j.from].push(j.to);radj[j.to].push(j.from);undir[j.from].push(j.to);undir[j.to].push(j.from);});

  securedTables=MODEL.tables.filter(t=>t.rls&&t.rls.length).map(t=>t.id);
  rlsAffected=new Set();
  securedTables.forEach(s=>ancestors(s).forEach(a=>rlsAffected.add(a)));

  LS_KEY="ts-erd-layout:"+MODEL.model.name;
  savedPos=loadSaved();

  _seed=20260627;
  nodes=MODEL.tables.map((t,i)=>{const a=i/MODEL.tables.length*Math.PI*2;
    return {t,w:NODE_W,h:nodeHeight(t),x:480+Math.cos(a)*240+(rnd()-.5)*40,y:340+Math.sin(a)*200+(rnd()-.5)*40};});
  nodeById={};nodes.forEach(n=>nodeById[n.t.id]=n);
  edges=MODEL.joins.map(j=>({j,s:nodeById[j.from],t:nodeById[j.to]}));

  layoutCache={organic:computeOrganic()};
  focusSet=[];selected=null;rlsOnly=false;
  tRlsOnly.checked=false;

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

$("finder").addEventListener("change",e=>{const id=e.target.value.trim();if(tableById[id]){selectTable(id,false);centerOn(nodeById[id]);e.target.value="";}});

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
