#!/usr/bin/env node
/* Source-system simulator (stands in for ERP / WMS).
   Seeded, so every run produces identical data. Writes RAW operational extracts to data/raw/.
   Usage: node tools/simulate_source.js [outDir]                                              */
'use strict';
const fs=require('fs'),path=require('path');
const OUT=process.argv[2]||path.join(__dirname,'..','data','raw');fs.mkdirSync(OUT,{recursive:true});
/* =====================================================================
   1. UTILITIES
   ===================================================================== */
function mulberry32(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
const rnd=mulberry32(20261029);
function gauss(){let u=0,v=0;while(!u)u=rnd();while(!v)v=rnd();return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v)}

const DAY=864e5;
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function inr(v){const a=Math.abs(v),s=v<0?'−':'';if(a>=1e7)return s+'₹'+(a/1e7).toFixed(2)+' Cr';if(a>=1e5)return s+'₹'+(a/1e5).toFixed(a>=1e6?1:2)+' L';return s+'₹'+Math.round(a).toLocaleString('en-IN')}
const n0=v=>Math.round(v).toLocaleString('en-IN');
const pc=(v,d=1)=>(v*100).toFixed(d)+'%';
const fdt=ms=>{const d=new Date(ms);return d.getUTCDate()+' '+MON[d.getUTCMonth()]};
const fdy=ms=>{const d=new Date(ms);return d.getUTCDate()+' '+MON[d.getUTCMonth()]+' '+d.getUTCFullYear()};
const esc=s=>String(s).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const Ztab={0.90:1.28,0.95:1.65,0.97:1.88,0.98:2.05,0.99:2.33};

/* =====================================================================
   2. MASTER DATA  (dimensions)
   ===================================================================== */
const W=80, WARM=60, D=W*7, TD=D+WARM;                 // 80 weeks of history (+60 warm-up days)
const ASOF=Date.UTC(2026,9,18);                         // Sun 18 Oct 2026 = end of last full week
const DATE0=ASOF-(D-1)*DAY;                             // a Monday (7 Apr 2025)
const wkStart=w=>DATE0+w*7*DAY;

const WH=[
 {id:'NGP',name:'Nagpur',region:'Central',size:1.00},
 {id:'BHW',name:'Bhiwandi',region:'West',size:1.55},
 {id:'PNQ',name:'Pune',region:'West',size:1.20},
 {id:'IDR',name:'Indore',region:'Central',size:0.80},
 {id:'RPR',name:'Raipur',region:'Central',size:0.60},
 {id:'HYD',name:'Hyderabad',region:'South',size:1.30}];
const NWH=WH.length;
const CATS=[
 {id:'STP',name:'Staples',short:'Staples',shelf:0,fest:0.60,holi:0.05,summer:0,cost:[60,880],base:[5,42],moq:[24,60],pack:6,sups:[[1,.55],[7,.45]],elig:[1,7,8,9,10,5]},
 {id:'OIL',name:'Edible oils',short:'Oils',shelf:0,fest:0.85,holi:0.05,summer:0,cost:[140,1800],base:[4,30],moq:[24,48],pack:6,sups:[[0,.55],[1,.45]],elig:[0,1,11,12,5]},
 {id:'PKG',name:'Packaged foods',short:'Packaged',shelf:0,fest:0.70,holi:0.25,summer:0,cost:[40,420],base:[3,30],moq:[60,120],pack:12,sups:[[4,.5],[5,.5]],elig:[4,5,15,9]},
 {id:'BEV',name:'Beverages',short:'Beverages',shelf:0,fest:0.20,holi:0.30,summer:0.35,cost:[120,520],base:[4,40],moq:[36,72],pack:6,sups:[[3,1]],elig:[3,13,18,5]},
 {id:'DRY',name:'Dairy & chilled',short:'Dairy',shelf:21,fest:0.35,holi:0.15,summer:0.08,cost:[90,700],base:[40,220],moq:[12,24],pack:12,sups:[[2,1]],elig:[2,14,16]},
 {id:'HCP',name:'Home & personal care',short:'Home care',shelf:0,fest:0.50,holi:0.05,summer:0,cost:[60,600],base:[3,28],moq:[24,60],pack:12,sups:[[5,.4],[6,.6]],elig:[5,6,17,19]}];
const NAMES=[
 ['Whole Wheat Atta 5 kg','Whole Wheat Atta 10 kg','Multigrain Atta 5 kg','Sharbati Atta 10 kg','Basmati Rice 1 kg','Basmati Rice 5 kg','Sona Masoori Rice 5 kg','Sona Masoori Rice 25 kg','Poha 500 g','Rice Flour 1 kg','Toor Dal 1 kg','Toor Dal 5 kg','Moong Dal 1 kg','Chana Dal 1 kg','Chana Dal 5 kg','Masoor Dal 1 kg','Urad Dal 1 kg','Rajma 1 kg','Kabuli Chana 1 kg','Sugar 1 kg','Sugar 5 kg','Rock Salt 1 kg','Iodised Salt 1 kg','Jaggery 1 kg','Besan 1 kg','Sooji 1 kg','Maida 1 kg','Vermicelli 400 g'],
 ['Sunflower Oil 1 L','Sunflower Oil 5 L','Sunflower Oil 15 L tin','Groundnut Oil 1 L','Groundnut Oil 5 L','Mustard Oil 1 L','Mustard Oil 5 L','Soybean Oil 1 L','Soybean Oil 5 L','Rice Bran Oil 1 L','Rice Bran Oil 5 L','Sesame Oil 500 ml','Coconut Oil 500 ml','Ghee 1 L'],
 ['Instant Noodles Masala 12-pk','Instant Noodles Veg 12-pk','Tea Dust 500 g','Tea Premium 250 g','Instant Coffee 100 g','Glucose Biscuits 800 g','Cream Biscuits 600 g','Butter Cookies 400 g','Bhujia Namkeen 400 g','Mixture Namkeen 400 g','Potato Chips 12-pk','Peanut Butter 500 g','Mango Pickle 500 g','Tomato Ketchup 1 kg','Soya Chunks 200 g','Cornflakes 475 g','Oats 1 kg','Muesli 500 g','Chocolate Bar Box 24','Hot Chocolate Mix 200 g','Papad 200 g','Pasta 500 g','Mayonnaise 450 g','Honey 500 g','Mixed Fruit Jam 500 g','Garam Masala 100 g','Turmeric Powder 200 g','Red Chilli Powder 200 g','Coriander Powder 200 g','Cumin Seeds 200 g'],
 ['Cola 2 L 6-pk','Cola 750 ml 12-pk','Lemon Soda 750 ml 12-pk','Orange Drink 1.2 L 6-pk','Mango Drink 1.2 L 6-pk','Mango Drink 200 ml 24-pk','Packaged Water 1 L 12-pk','Packaged Water 20 L jar','Energy Drink 250 ml 24-pk','Electrolyte Drink 500 ml 12-pk','Apple Juice 1 L 6-pk','Mixed Fruit Juice 1 L 6-pk','Coconut Water 200 ml 24-pk','Iced Tea 500 ml 12-pk','Cold Coffee 200 ml 24-pk','Soda Water 750 ml 12-pk','Tonic Water 300 ml 24-pk','Sports Drink 600 ml 12-pk'],
 ['Full-Cream Milk 500 ml','Toned Milk 500 ml','Curd 400 g','Curd 1 kg','Paneer 200 g','Butter 500 g','Cheese Slices 200 g','Flavoured Milk 200 ml','Buttermilk 200 ml','Lassi 200 ml','Cream 200 ml','Cheese Block 1 kg'],
 ['Detergent Powder 1 kg','Detergent Powder 4 kg','Detergent Liquid 1 L','Dish Wash Gel 750 ml','Dish Wash Bar 3-pk','Floor Cleaner 1 L','Toilet Cleaner 500 ml','Bath Soap 4-pk','Bath Soap Premium 3-pk','Shampoo 340 ml','Shampoo Sachet Strip','Toothpaste 150 g 6-pk','Toothbrush 4-pk','Hand Wash 750 ml','Body Lotion 400 ml','Hair Oil 500 ml','Sanitary Pads 20s','Face Wash 100 ml']];
const SUP=[
 {id:0,name:'Gujarat Edible Oils Ltd',short:'Gujarat Oils',planL:5,planSd:1.0,m:5.0,sd:1.0,ifp:.95,spend:0},
 {id:1,name:'Vidarbha Agro Mills',short:'Vidarbha Agro',planL:4,planSd:1.0,m:4.0,sd:1.0,ifp:.93,spend:0},
 {id:2,name:'Sahyadri Dairy Co-op',short:'Sahyadri Dairy',planL:2,planSd:0.5,m:2.0,sd:0.5,ifp:.97,spend:0},
 {id:3,name:'Deccan Beverages Pvt Ltd',short:'Deccan Bev.',planL:6,planSd:1.0,m:6.6,sd:1.3,ifp:.92,spend:0},
 {id:4,name:'Malwa Foods & Spices',short:'Malwa Foods',planL:7,planSd:1.2,m:7.0,sd:1.5,ifp:.90,spend:0},
 {id:5,name:'Bharat FMCG Distributors',short:'Bharat FMCG',planL:3,planSd:0.8,m:3.0,sd:0.8,ifp:.95,spend:0},
 {id:6,name:'Konkan Home Care Ltd',short:'Konkan HC',planL:5,planSd:1.0,m:5.0,sd:1.2,ifp:.93,spend:0},
 {id:7,name:'Telangana Rice & Pulses',short:'Telangana R&P',planL:6,planSd:1.2,m:6.0,sd:1.2,ifp:.94,spend:0},
 {id:8,name:'Rajasthan Grain Traders',short:'Rajasthan Grain',planL:5,planSd:1.0,m:5.2,sd:1.0,ifp:.92,spend:0},
 {id:9,name:'Punjab Agro Foods',short:'Punjab Agro',planL:6,planSd:1.1,m:6.0,sd:1.2,ifp:.94,spend:0},
 {id:10,name:'Hyderabad Pulses Co.',short:'Hyd Pulses',planL:3,planSd:0.8,m:3.1,sd:0.9,ifp:.96,spend:0},
 {id:11,name:'Kerala Coconut Oil Mills',short:'Kerala Oil',planL:8,planSd:1.5,m:8.0,sd:1.6,ifp:.90,spend:0},
 {id:12,name:'Maharashtra Oil Refiners',short:'MH Refiners',planL:4,planSd:0.9,m:4.0,sd:1.0,ifp:.95,spend:0},
 {id:13,name:'Nashik Fruit Beverages',short:'Nashik Bev.',planL:4,planSd:1.0,m:4.1,sd:1.1,ifp:.93,spend:0},
 {id:14,name:'Malwa Milk Union',short:'Malwa Milk',planL:3,planSd:0.6,m:3.0,sd:0.7,ifp:.96,spend:0},
 {id:15,name:'Pune Packaged Foods Ltd',short:'Pune Packaged',planL:5,planSd:1.0,m:5.0,sd:1.0,ifp:.94,spend:0},
 {id:16,name:'Coastal Dairy Works',short:'Coastal Dairy',planL:2,planSd:0.5,m:2.1,sd:0.5,ifp:.95,spend:0},
 {id:17,name:'Indus Home Products',short:'Indus Home',planL:4,planSd:1.0,m:4.2,sd:1.1,ifp:.93,spend:0},
 {id:18,name:'Sagar Beverages',short:'Sagar Bev.',planL:7,planSd:1.3,m:7.2,sd:1.4,ifp:.91,spend:0},
 {id:19,name:'Eastern Care Industries',short:'Eastern Care',planL:6,planSd:1.2,m:6.1,sd:1.3,ifp:.92,spend:0}];
const DRIFT_START=420, DRIFT_END=500;   // Vidarbha lead time creep (days index)
function supM(s,t){ if(s.id!==1||t<DRIFT_START) return [s.m,s.sd]; const f=clamp((t-DRIFT_START)/(DRIFT_END-DRIFT_START),0,1); return [s.m+f*4.3, s.sd+f*1.6]; }

/* Realistic purchase cost from the pack size in the product name (price per kg / L x size, or price per piece x count).
   RULES: [name regex, low, high, mode]  mode 'w' = Rs per kg or litre, 'u' = Rs per piece.  q in [0,1) places the SKU inside the range. */
const RATES=[
 [/Ghee/,520,640,'w'],[/^Hair Oil/,220,400,'w'],[/^(Iced Tea)/,60,95,'w'],[/^Cold Coffee/,150,230,'w'],[/Sesame|Coconut Oil/,250,420,'w'],[/Mustard/,140,190,'w'],[/Groundnut/,150,210,'w'],[/^(Sunflower|Soybean|Rice Bran)/,105,150,'w'],
 [/Basmati/,95,130,'w'],[/Sona Masoori/,52,68,'w'],[/Rice Flour|Atta|Sooji|Maida|Besan|Poha/,34,56,'w'],[/Dal|Rajma|Chana|Kabuli/,85,160,'w'],
 [/Sugar/,38,46,'w'],[/Salt/,16,32,'w'],[/Jaggery/,55,75,'w'],[/Vermicelli/,60,90,'w'],
 [/Noodles/,10,15,'u'],[/Chips/,8,18,'u'],[/Chocolate Bar/,8,35,'u'],[/^Tea /,250,600,'w'],[/^Instant Coffee/,1200,2200,'w'],[/Biscuits|Cookies/,70,130,'w'],[/Namkeen|Bhujia/,110,200,'w'],
 [/Peanut Butter/,220,420,'w'],[/Pickle/,110,200,'w'],[/Ketchup/,90,140,'w'],[/Soya Chunks/,100,150,'w'],[/Cornflakes/,160,240,'w'],[/Oats/,110,170,'w'],[/Muesli/,250,420,'w'],
 [/Hot Chocolate/,350,560,'w'],[/Papad/,150,260,'w'],[/Pasta/,90,150,'w'],[/Mayonnaise/,140,230,'w'],[/Honey/,300,520,'w'],[/Jam/,140,230,'w'],
 [/Garam Masala/,700,1100,'w'],[/Turmeric/,150,260,'w'],[/Red Chilli/,250,420,'w'],[/Coriander/,140,240,'w'],[/Cumin/,380,640,'w'],
 [/Cola/,38,55,'w'],[/Soda|Tonic/,30,50,'w'],[/Orange|Mango|Apple|Juice/,55,110,'w'],[/Packaged Water 20/,3,5,'w'],[/Water 1 L/,9,14,'w'],[/Energy/,160,280,'w'],[/Electrolyte/,90,160,'w'],
 [/Sports/,100,170,'w'],[/Coconut Water/,90,150,'w'],
 [/Milk 500|Toned/,48,56,'w'],[/Curd/,72,100,'w'],[/Paneer/,330,420,'w'],[/Butter 500/,480,540,'w'],[/Cheese Slices/,420,560,'w'],[/Flavoured/,70,100,'w'],[/Buttermilk/,28,40,'w'],[/Lassi/,55,80,'w'],
 [/Cream/,240,320,'w'],[/Cheese Block/,440,560,'w'],
 [/Detergent Powder/,95,170,'w'],[/Detergent Liquid/,150,240,'w'],[/Dish Wash Gel/,130,210,'w'],[/Dish Wash Bar/,12,24,'u'],[/Floor/,90,170,'w'],[/Toilet/,150,240,'w'],
 [/Bath Soap Premium/,48,85,'u'],[/Bath Soap/,24,40,'u'],[/Shampoo Sachet/,1.2,2.4,'u'],[/Shampoo/,260,520,'w'],[/Toothpaste/,48,85,'u'],[/Toothbrush/,18,40,'u'],[/Hand Wash/,120,200,'w'],
 [/Body Lotion/,320,520,'w'],[/Sanitary/,4.2,7.5,'u'],[/Face Wash/,520,900,'w']];
function realCost(name,q){
  const r=RATES.find(x=>x[0].test(name)); if(!r) return 100;
  const rate=r[1]*Math.pow(r[2]/r[1],q);
  let amt=1,m;
  if((m=name.match(/(\d+(?:\.\d+)?)\s*kg/i)))amt=+m[1];else if((m=name.match(/(\d+(?:\.\d+)?)\s*L\b/)))amt=+m[1];
  else if((m=name.match(/(\d+(?:\.\d+)?)\s*g\b/)))amt=+m[1]/1000;else if((m=name.match(/(\d+(?:\.\d+)?)\s*ml/i)))amt=+m[1]/1000;
  let cnt=1; if((m=name.match(/(\d+)-pk/)))cnt=+m[1]; else if((m=name.match(/Box (\d+)/)))cnt=+m[1]; else if((m=name.match(/(\d+)s$/)))cnt=+m[1]; else if(/Strip/.test(name))cnt=10;
  if(/Toothpaste/.test(name)||/Dish Wash Bar|Bath Soap|Toothbrush/.test(name)) amt=1;     // priced per piece
  const v=r[3]==='w'?rate*amt*(/-pk/.test(name)&&!/Noodles|Chips/.test(name)?cnt:1):rate*cnt*(/Noodles|Chips/.test(name)?1:1);
  return Math.max(3,Math.round(v));
}
const SKUS=[];
(function(){
  let k=1001;
  CATS.forEach((ct,ci)=>{
    NAMES[ci].forEach((nm,j)=>{
      const u=rnd(), cost=realCost(nm,rnd());
      const margin=.08+.14*rnd();
      const bu=Math.pow(rnd(),1.8);
      const base=ct.base[0]*Math.pow(ct.base[1]/ct.base[0],bu);
      let r=rnd(),sup=ct.sups[0][0],acc=0; for(const [s,p] of ct.sups){acc+=p; if(r<=acc){sup=s;break}}
      const xr=rnd(); const xyz=xr<.45?'X':(xr<.80?'Y':'Z');
      const cv=xyz==='X'?.22+.2*rnd():(xyz==='Y'?.55+.3*rnd():1.2);
      SKUS.push({i:SKUS.length,code:'SKU-'+(k++),name:nm,cat:ci,cost,price:Math.round(cost*(1+margin)),base,cv,z:xyz==='Z',
        moq:Math.round(ct.moq[0]+(ct.moq[1]-ct.moq[0])*rnd()),pack:ct.pack,sup,dead:false,tier:'C',u});
    });
  });
  // sim-side tier by value rank (policy uses it before dashboard re-derives ABC)
  const ord=SKUS.slice().sort((a,b)=>b.base*b.price-a.base*a.price);
  const tot=ord.reduce((s,x)=>s+x.base*x.price,0); let cum=0;
  ord.forEach(x=>{ x.tier=cum<.70*tot?'A':(cum<.90*tot?'B':'C'); cum+=x.base*x.price; });
  // planted story: 9 slow C-class SKUs in packaged / home care stop selling (delisted by a key customer)
  const cands=SKUS.filter(x=>x.tier==='C'&&(x.cat===2||x.cat===5));
  for(let n=0;n<9&&cands.length;n++){ const j=Math.floor(rnd()*cands.length); cands.splice(j,1)[0].dead=true; }
})();
// ---- sourcing panel: every SKU can be bought from 2-5 approved suppliers (own price, lead time, order share) ----
const rndS=mulberry32(77123);                    // separate stream: panel design does not disturb the main demand stream
const FORCE_N={'Basmati Rice 1 kg':5,'Basmati Rice 5 kg':5,'Toor Dal 1 kg':4,'Sunflower Oil 1 L':4};
SKUS.forEach(k=>{
  const ct=CATS[k.cat]; let n=FORCE_N[k.name]||2+Math.floor(rndS()*4); n=Math.min(n,ct.elig.length);
  const others=ct.elig.filter(e=>e!==k.sup);
  for(let i=others.length-1;i>0;i--){const j=Math.floor(rndS()*(i+1));[others[i],others[j]]=[others[j],others[i]];}
  const panel=[k.sup].concat(others.slice(0,n-1));
  const lt=panel.map((s,i)=>Math.max(1,SUP[s].planL+(i===0?0:[-1,0,0,1][Math.floor(rndS()*4)])));
  const price=panel.map((s,i)=>i===0?k.cost:+(k.cost*clamp(1+0.012*(lt[0]-lt[i])+(rndS()-.5)*.03,.92,1.09)).toFixed(2));
  let share=[1];
  if(n>1){const p0=.40+.20*rndS(),w=panel.slice(1).map(()=>.5+rndS()),sw=w.reduce((a,b)=>a+b,0);
    const rest=w.map(x=>+((1-p0)*x/sw).toFixed(2)); share=[+(1-rest.reduce((a,b)=>a+b,0)).toFixed(2)].concat(rest);}
  k.terms=panel.map((s,i)=>({sup:s,price:price[i],lt:lt[i],share:share[i],prim:i===0}));
  k.Leff=k.terms.reduce((a,t)=>a+t.share*t.lt,0); k.SDeff=k.terms.reduce((a,t)=>a+t.share*SUP[t.sup].planSd,0);
});
const NS=SKUS.length, C=NS*NWH;
const cf=new Float32Array(C); for(let c=0;c<C;c++) cf[c]=.85+.3*rnd();

/* =====================================================================
   3. CALENDAR  (festival intensity by day)
   ===================================================================== */
const FEST=[
 {n:'Holi',d:Date.UTC(2025,2,14)},{n:'Dussehra',d:Date.UTC(2025,9,2)},{n:'Diwali',d:Date.UTC(2025,9,20)},
 {n:'Holi',d:Date.UTC(2026,2,4)},{n:'Dussehra',d:Date.UTC(2026,9,20)},{n:'Diwali',d:Date.UTC(2026,10,8)}];
const festA=new Float32Array(TD), holiA=new Float32Array(TD), dowF=new Float32Array(TD), trendA=new Float32Array(TD), doyA=new Float32Array(TD);
for(let i=0;i<TD;i++){
  const ms=DATE0+(i-WARM)*DAY, dt=new Date(ms); let f=0,h=0;
  for(const e of FEST){const dd=(ms-e.d)/DAY;
    if(e.n==='Diwali') f=Math.max(f,Math.exp(-Math.pow((dd+8)/6,2)));
    else if(e.n==='Dussehra') f=Math.max(f,.35*Math.exp(-Math.pow((dd+4)/5,2)));
    else h=Math.max(h,Math.exp(-Math.pow((dd+3)/4,2)));}
  festA[i]=f; holiA[i]=h;
  const dw=dt.getUTCDay(); dowF[i]=dw===0?.72:(dw===6?.95:1.06);
  trendA[i]=1+.12*((i-WARM)/D);
  const start=Date.UTC(dt.getUTCFullYear(),0,0); doyA[i]=(ms-start)/DAY;
}
const seas=(ct,i)=>1+ct.summer*Math.cos(2*Math.PI*(doyA[i]-135)/365);

/* =====================================================================
   4. SIMULATION  (daily, per SKU × warehouse, (s,Q) policy)
   ===================================================================== */
const dem=new Float32Array(C*W), sal=new Float32Array(C*W), rcv=new Float32Array(C*W), ord=new Float32Array(C*W),
      wo=new Float32Array(C*W), demD=new Float32Array(C*D), salD=new Float32Array(C*D), rcvD=new Float32Array(C*D), ordD=new Float32Array(C*D), woD=new Float32Array(C*D), clsD=new Float32Array(C*D), ohE=new Float32Array(C*W), oos=new Uint8Array(C*W), act=new Uint8Array(C*W), d90=new Float32Array(C*90);
const PO={c:[],ord:[],recv:[],qty:[],got:[],sup:[],planL:[],price:[]};
const poByC=Array.from({length:C},()=>[]);
const BATCH=[]; const fin={oh:new Float32Array(C),onOrd:new Float32Array(C),age:new Float32Array(C*4),expU:new Float32Array(C*8)}; // expU: expiring units at horizon 1..8
const ZSIM={A:Ztab[0.98],B:Ztab[0.95],C:Ztab[0.90]};

(function simulate(){
  for(let c=0;c<C;c++){
    const sk=SKUS[(c/NWH)|0], wi=c%NWH, ct=CATS[sk.cat];
    const d0=sk.base*WH[wi].size*cf[c];
    const ring=new Float32Array(28); let rs=0,rq=0;
    for(let k=0;k<28;k++){ring[k]=d0;} rs=28*d0; rq=28*(d0*d0+Math.pow(sk.cv*d0,2));
    let oh=Math.round(d0*(sk.Leff+10)); const batches=[{q:oh,d:-8}]; const pend=[];
    for(let i=0;i<TD;i++){
      const t=i-WARM, w=t>=0?(t/7|0):-1, ix=c*W+w;
      // 1) receipts arriving today
      for(let k=pend.length-1;k>=0;k--){ const p=pend[k]; if(p.day<=i){ batches.push({q:p.got,d:i}); oh+=p.got; if(w>=0){rcv[ix]+=p.got; rcvD[c*D+t]+=p.got;} PO.recv[p.po]=t; pend.splice(k,1); } }
      // planted: Hyderabad beverages bulk promo buy (≈70 days of stock) at day 405
      if(t===405&&wi===5&&sk.cat===3){ const q=Math.round(55*rs/28/sk.pack)*sk.pack; batches.push({q,d:i}); oh+=q; rcv[ix]+=q; rcvD[c*D+t]+=q; PO.c.push(c);PO.ord.push(t-6);PO.recv.push(t);PO.qty.push(q);PO.got.push(q);PO.sup.push(sk.sup);PO.planL.push(sk.terms[0].lt);PO.price.push(sk.terms[0].price); poByC[c].push(PO.c.length-1); }
      // 2) expiry (dairy)
      if(ct.shelf){ while(batches.length&&i-batches[0].d>=ct.shelf){ const b=batches.shift(); oh-=b.q; if(w>=0){wo[ix]+=b.q; woD[c*D+t]+=b.q;} } }
      // 3) demand
      let mu=d0*trendA[i]*dowF[i]*(1+ct.fest*festA[i])*(1+ct.holi*holiA[i])*seas(ct,i);
      if(wi===5&&sk.cat===3&&t>=410) mu*=.60;             // Hyderabad beverages slump
      if(wi===3&&sk.cat===4&&t>=470) mu*=.62;             // Indore dairy slump
      let dm;
      if(sk.dead&&t>=400) dm=0;
      else if(sk.z) dm=rnd()<.35?Math.max(0,Math.round(mu/.35*Math.exp(.5*gauss()-.125))):0;
      else dm=Math.max(0,Math.round(mu+sk.cv*mu*gauss()));
      const old=ring[i%28]; rs+=dm-old; rq+=dm*dm-old*old; ring[i%28]=dm;
      // 4) sales FIFO
      let s=Math.min(oh,dm); let need=s; while(need>0&&batches.length){ const b=batches[0]; if(b.q<=need){need-=b.q;batches.shift()}else{b.q-=need;need=0} } oh-=s;
      // 5) review & order
      const dHat=rs/28, sd=Math.sqrt(Math.max(0,rq/28-dHat*dHat));
      if(dHat>0.05&&!(sk.dead&&t>=400)){
        const ss=ZSIM[sk.tier]*Math.sqrt(sk.Leff*sd*sd+dHat*dHat*sk.SDeff*sk.SDeff), rop=dHat*sk.Leff+ss;
        let pq=0; for(const p of pend) pq+=p.qty;
        if(oh+pq<=rop){
          let q=Math.sqrt(2*dHat*365*3000/(sk.cost*.25)); q=Math.max(Math.min(q,(ct.shelf?ct.shelf*.5:45)*dHat),sk.moq); q=Math.ceil(q/sk.pack)*sk.pack;
          const mult=Math.max(1,Math.ceil((rop-(oh+pq)+1)/q)); const qty=q*mult;
          let r2=rndS(),acc2=0,tm=sk.terms[0]; for(const t2 of sk.terms){acc2+=t2.share; if(r2<=acc2){tm=t2;break}}   // which panel supplier gets this PO
          const sps=SUP[tm.sup]; const [m,sdv]=supM(sps,t); const L=Math.max(1,Math.round(m+(tm.lt-sps.planL)+sdv*gauss()));
          const got=rnd()<sps.ifp?qty:Math.round(qty*(.70+.28*rnd())/sk.pack)*sk.pack;
          PO.c.push(c);PO.ord.push(t);PO.recv.push(-999);PO.qty.push(qty);PO.got.push(got);PO.sup.push(tm.sup);PO.planL.push(tm.lt);PO.price.push(tm.price);
          const pid=PO.c.length-1; poByC[c].push(pid);
          pend.push({day:i+L,qty,got,po:pid}); if(w>=0){ord[ix]+=qty; ordD[c*D+t]+=qty;}
        }
      }
      // 6) record
      if(w>=0){
        dem[ix]+=dm; sal[ix]+=s; act[ix]++; demD[c*D+t]=dm; salD[c*D+t]=s; clsD[c*D+t]=oh; if(oh<=0) oos[ix]++;
        if(t%7===6) ohE[ix]=oh;
        if(t>=D-90) d90[c*90+(t-(D-90))]=dm;
      }
    }
    // final state
    BATCH.push([c,batches.map(b=>[b.d-WARM,b.q])]); fin.oh[c]=oh; let pq=0; for(const p of pend) pq+=p.qty; fin.onOrd[c]=pq;
    const last=TD-1;
    for(const b of batches){ const a=last-b.d; fin.age[c*4+(a<=30?0:a<=60?1:a<=90?2:3)]+=b.q;
      if(ct.shelf){ const left=ct.shelf-a; for(let h=1;h<=8;h++) if(left<=h) fin.expU[c*8+h-1]+=b.q; } }
  }
  // forecast = exponential smoothing on weekly demand (alpha .3), forecast for week w made at end of w-1
})();
const fc=new Float32Array(C*W);
for(let c=0;c<C;c++){ let f=dem[c*W]; fc[c*W]=f; for(let w=1;w<W;w++){ f=.3*dem[c*W+w-1]+.7*f; fc[c*W+w]=f; } }
// mark POs ordered but not received by end as open (recv stays -999)
SUP.forEach(s=>s.spend=0);


/* =================== WRITE RAW EXTRACTS =================== */
const iso=ms=>new Date(ms).toISOString().slice(0,10);
const dOf=t=>iso(DATE0+t*DAY);
const q=v=>/[",\n]/.test(String(v))?'"'+String(v).replace(/"/g,'""')+'"':String(v);
const wr=(f,rows)=>fs.writeFileSync(path.join(OUT,f),rows.join('\n')+'\n');
wr('category_master.csv',['category_id,category_name,short_name,shelf_life_days'].concat(CATS.map(c=>[c.id,q(c.name),c.short,c.shelf].join(','))));
wr('warehouse_master.csv',['wh_id,wh_name,region,size_index'].concat(WH.map(w=>[w.id,w.name,w.region,w.size].join(','))));
wr('supplier_master.csv',['supplier_id,supplier_name,short_name,planned_lead_time_days,planned_lead_time_sd_days'].concat(SUP.map(s=>['SUP-'+(s.id+1),q(s.name),q(s.short),s.planL,s.planSd].join(','))));
wr('sku_master.csv',['sku_id,sku_name,category_id,unit_cost_inr,mrp_inr,moq_units,case_pack_units,primary_supplier_id'].concat(SKUS.map(k=>[k.code,q(k.name),CATS[k.cat].id,k.cost,k.price,k.moq,k.pack,'SUP-'+(k.sup+1)].join(','))));
wr('sku_supplier_terms.csv',['sku_id,supplier_id,is_primary,quoted_unit_price_inr,quoted_lead_time_days,allocation_share'].concat(SKUS.flatMap(k=>k.terms.map(t=>[k.code,'SUP-'+(t.sup+1),t.prim?1:0,t.price,t.lt,t.share].join(',')))));
wr('festival_calendar.csv',['festival,date'].concat(FEST.map(f=>f.n+','+iso(f.d))));
// daily movements (one row per SKU x warehouse x day)
{const rows=['date,sku_id,wh_id,demand_units,sales_units,receipts_units,orders_placed_units,writeoff_units,closing_stock_units'];
 const dstr=[];for(let t=0;t<D;t++)dstr.push(dOf(t));
 const fd=fs.openSync(path.join(OUT,'daily_movements.csv'),'w');fs.writeSync(fd,rows[0]+'\n');
 for(let c=0;c<C;c++){const sk=SKUS[(c/NWH)|0].code,wh=WH[c%NWH].id;let buf=[];for(let t=0;t<D;t++){const k=c*D+t;buf.push(dstr[t]+','+sk+','+wh+','+demD[k]+','+salD[k]+','+rcvD[k]+','+ordD[k]+','+woD[k]+','+clsD[k]);}fs.writeSync(fd,buf.join('\n')+'\n');}
 fs.closeSync(fd);}
// purchase-order lines (only those received inside the window, or still open)
{const rows=['po_line_id,sku_id,wh_id,supplier_id,order_date,promised_date,received_date,qty_ordered,qty_received,unit_price_inr'];
 for(let p=0;p<PO.c.length;p++){const r=PO.recv[p];if(r!==-999&&r<0)continue;const c=PO.c[p];
  rows.push(['PO-'+(10000+p),SKUS[(c/NWH)|0].code,WH[c%NWH].id,'SUP-'+(PO.sup[p]+1),dOf(PO.ord[p]),dOf(PO.ord[p]+PO.planL[p]),r===-999?'':dOf(r),PO.qty[p],r===-999?0:PO.got[p],PO.price[p]].join(','));}
 wr('purchase_order_lines.csv',rows);}
// batch / lot report at the as-of date (what the WMS shows)
{const rows=['sku_id,wh_id,received_date,qty_on_hand'];for(const [c,bs] of BATCH)for(const [t,qq] of bs)if(qq>0)rows.push([SKUS[(c/NWH)|0].code,WH[c%NWH].id,dOf(t),qq].join(','));wr('stock_batches.csv',rows);}
console.log('raw extracts written to',OUT);
