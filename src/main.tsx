import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  BadgeCheck, Bell, Bot, BriefcaseBusiness, Check, CheckCircle2, ChevronRight,
  CircleDollarSign, Clock3, Droplets, Hammer, Home, MapPin, Menu, MessageCircle,
  Paintbrush, Plus, Search, ShieldCheck, Snowflake, Sparkles, Star, Truck,
  UserRound, UsersRound, WandSparkles, Wrench, X, Zap
} from 'lucide-react';
import './styles.css';

type Role = 'customer' | 'provider';
type View = 'home' | 'jobs' | 'messages' | 'profile';
type JobStatus = 'Open' | 'Booked' | 'On the way' | 'In progress' | 'Awaiting confirmation' | 'Completed';

type AiAnalysis = {
  category: string;
  urgency: 'Low' | 'Medium' | 'High';
  duration: string;
  range: string;
  summary: string;
  questions: string[];
  risk: string;
};

type Job = {
  id: number;
  title: string;
  category: string;
  location: string;
  budget: string;
  timing: string;
  description: string;
  status: JobStatus;
  createdAt: string;
  ai: AiAnalysis;
  acceptedBidId?: number;
};

type Bid = {
  id: number;
  jobId: number;
  provider: string;
  profession: string;
  rating: number;
  reviews: number;
  price: number;
  arrival: string;
  warranty: string;
  message: string;
  verified: boolean;
  completionRate: number;
};

type Message = { id: number; from: 'me' | 'other'; text: string; time: string };

const categories = [
  { name: 'Plumbing', icon: Droplets }, { name: 'Electrical', icon: Zap },
  { name: 'AC & Cooling', icon: Snowflake }, { name: 'Painting', icon: Paintbrush },
  { name: 'Cleaning', icon: Sparkles }, { name: 'Moving', icon: Truck },
  { name: 'Carpentry', icon: Hammer }, { name: 'General repair', icon: Wrench },
];

const defaultAnalysis: AiAnalysis = {
  category: 'Plumbing', urgency: 'Medium', duration: '30–60 minutes', range: 'JOD 25–45',
  summary: 'Likely a loose connection, worn seal, or drain-trap issue. A professional inspection is recommended today.',
  questions: ['Does the leak happen only while the tap is running?', 'Can you see whether it comes from a joint or the drain?'],
  risk: 'Turn off the local water valve if the leak becomes continuous.'
};

const seededJobs: Job[] = [
  { id: 1, title: 'Kitchen sink is leaking', category: 'Plumbing', location: 'Khalda, Amman', budget: 'JOD 25–45', timing: 'Today', description: 'Leak under the kitchen sink. It gets worse when the tap is running.', status: 'Open', createdAt: 'Today, 10:20', ai: defaultAnalysis },
  { id: 2, title: 'Install two ceiling lights', category: 'Electrical', location: 'Abdoun, Amman', budget: 'JOD 30–60', timing: 'This week', description: 'Replace two ceiling fixtures with LED fittings.', status: 'Booked', createdAt: 'Yesterday', ai: { category:'Electrical',urgency:'Low',duration:'60–90 minutes',range:'JOD 30–60',summary:'Standard fixture replacement. Existing wiring should be checked before installation.',questions:['Are the new fixtures already purchased?'],risk:'Power must be isolated before work begins.' }, acceptedBidId: 4 },
  { id: 3, title: 'AC not cooling properly', category: 'AC & Cooling', location: 'Dabouq, Amman', budget: 'Open to bids', timing: 'Tomorrow', description: 'Split AC runs but the room remains warm and there is a clicking sound.', status: 'On the way', createdAt: 'Today, 08:45', ai: { category:'AC & Cooling',urgency:'Medium',duration:'30–90 minutes',range:'JOD 25–70',summary:'Possible fan obstruction, capacitor issue, filter blockage, or refrigerant problem.',questions:['Does the outdoor unit make the clicking sound?'],risk:'Stop using the unit if there is a burning smell or electrical noise.' }, acceptedBidId: 7 },
];

const seededBids: Bid[] = [
  { id:1,jobId:1,provider:'Ahmad Al-Khatib',profession:'Licensed Plumber',rating:4.9,reviews:126,price:32,arrival:'Within 60 minutes',warranty:'30 days',message:'Includes diagnosis, labor, and standard fittings. Any major replacement part will be approved first.',verified:true,completionRate:98 },
  { id:2,jobId:1,provider:'Omar Maintenance',profession:'Home Maintenance Team',rating:4.8,reviews:84,price:38,arrival:'Today at 4:00 PM',warranty:'45 days',message:'Two-person team available. Price includes the visit and minor materials.',verified:true,completionRate:97 },
  { id:3,jobId:1,provider:'Yousef Haddad',profession:'Plumber & Handyman',rating:4.7,reviews:51,price:28,arrival:'Today at 6:30 PM',warranty:'14 days',message:'Available this evening. Common replacement parts are available.',verified:false,completionRate:91 },
  { id:4,jobId:2,provider:'Rami Electric',profession:'Certified Electrician',rating:4.9,reviews:210,price:46,arrival:'Thursday at 10:00 AM',warranty:'60 days',message:'Includes installation, testing, and safe disposal of old fixtures.',verified:true,completionRate:99 },
  { id:7,jobId:3,provider:'Sami HVAC',profession:'HVAC Technician',rating:4.9,reviews:178,price:45,arrival:'ETA 18 minutes',warranty:'30 days',message:'Diagnosis and minor repair labor included. Replacement parts require approval.',verified:true,completionRate:98 },
];

const STORAGE_KEY = 'khidmati-mvp-state-v2';

function analyzeRequest(text: string, title: string): AiAnalysis {
  const v = `${title} ${text}`.toLowerCase();
  if (/ac|air condition|cool|compressor|مكيف/.test(v)) return { category:'AC & Cooling',urgency:/smell|smoke|spark|burn/.test(v)?'High':'Medium',duration:'30–90 minutes',range:'JOD 25–70',summary:'Likely filter, fan, capacitor, relay, or refrigerant issue. A technician should inspect the unit before parts are replaced.',questions:['Does the outdoor unit make the same sound?','When was the filter last cleaned?'],risk:'Stop the unit immediately if there is smoke, burning smell, or exposed wiring.' };
  if (/electric|light|socket|power|breaker|spark|كهرب/.test(v)) return { category:'Electrical',urgency:/spark|smoke|burn|exposed/.test(v)?'High':'Medium',duration:'30–120 minutes',range:'JOD 20–80',summary:'Possible fixture, connection, breaker, or wiring fault. A qualified electrician should test the circuit.',questions:['Has the breaker tripped?','Is there heat, smell, or visible damage?'],risk:'Do not touch exposed wiring. Isolate the circuit when safe.' };
  if (/paint|wall|ceiling|دهان/.test(v)) return { category:'Painting',urgency:'Low',duration:'2–8 hours',range:'JOD 40–180',summary:'The work likely requires surface preparation, minor repair, primer, and paint. Final cost depends on area and material.',questions:['What is the approximate area?','Will you provide the paint?'],risk:'Confirm ventilation and protect furniture and floors.' };
  if (/move|moving|furniture|نقل/.test(v)) return { category:'Moving',urgency:'Low',duration:'2–6 hours',range:'JOD 40–160',summary:'The job requires vehicle size, access, floor level, and item count to produce an accurate quote.',questions:['Are there stairs or elevators?','How many large items are included?'],risk:'List fragile or high-value items before accepting a bid.' };
  if (/clean|تنظيف/.test(v)) return { category:'Cleaning',urgency:'Low',duration:'2–5 hours',range:'JOD 25–90',summary:'Cleaning scope should specify property size, furnishing, supplies, and any deep-cleaning areas.',questions:['How many rooms and bathrooms?','Should the professional bring supplies?'],risk:'Secure valuables and disclose pets or access restrictions.' };
  return defaultAnalysis;
}

function loadState(): { jobs: Job[]; bids: Bid[] } {
  try { const raw = localStorage.getItem(STORAGE_KEY); if (raw) return JSON.parse(raw); } catch { /* ignore */ }
  return { jobs: seededJobs, bids: seededBids };
}

function App() {
  const saved = useMemo(loadState, []);
  const [role, setRole] = useState<Role>('customer');
  const [view, setView] = useState<View>('home');
  const [jobs, setJobs] = useState<Job[]>(saved.jobs);
  const [bids, setBids] = useState<Bid[]>(saved.bids);
  const [query, setQuery] = useState('');
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [showPost, setShowPost] = useState(false);
  const [toast, setToast] = useState('');

  useEffect(() => localStorage.setItem(STORAGE_KEY, JSON.stringify({ jobs, bids })), [jobs, bids]);
  const filteredJobs = jobs.filter(j => `${j.title} ${j.category} ${j.location}`.toLowerCase().includes(query.toLowerCase()));
  const notify = (message:string) => { setToast(message); window.setTimeout(()=>setToast(''),2500); };

  function createJob(input: Omit<Job,'id'|'status'|'createdAt'|'ai'> & { ai:AiAnalysis }) {
    const job: Job = { ...input, id:Date.now(), status:'Open', createdAt:'Just now' };
    setJobs(x=>[job,...x]); setShowPost(false); setView('jobs'); notify('Request published and matched to nearby professionals.');
  }
  function submitBid(jobId:number, bid:Omit<Bid,'id'|'jobId'>) {
    setBids(x=>[{...bid,id:Date.now(),jobId},...x]); notify('Bid submitted successfully.');
  }
  function acceptBid(jobId:number,bidId:number){ setJobs(x=>x.map(j=>j.id===jobId?{...j,status:'Booked',acceptedBidId:bidId}:j)); setSelectedJob(j=>j?{...j,status:'Booked',acceptedBidId:bidId}:j); notify('Bid accepted. The job scope is now locked.'); }
  function advanceJob(jobId:number){
    const order:JobStatus[]=['Booked','On the way','In progress','Awaiting confirmation','Completed'];
    setJobs(x=>x.map(j=>{if(j.id!==jobId)return j;const i=order.indexOf(j.status);return {...j,status:order[Math.min(i+1,order.length-1)]};}));
    setSelectedJob(j=>j&&j.id===jobId?{...j,status:order[Math.min(order.indexOf(j.status)+1,order.length-1)]}:j); notify('Job status updated.');
  }

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">خ</span><span>Khidmati</span><span className="ai-label"><Bot size={14}/> AI</span></div>
      <nav className="desktop-nav"><button className={view==='home'?'active':''} onClick={()=>setView('home')}>Explore</button><button className={view==='jobs'?'active':''} onClick={()=>setView('jobs')}>{role==='customer'?'My requests':'Jobs'}</button><button className={view==='messages'?'active':''} onClick={()=>setView('messages')}>Messages</button></nav>
      <div className="header-actions"><div className="role-toggle"><button className={role==='customer'?'selected':''} onClick={()=>{setRole('customer');setView('home')}}>Customer</button><button className={role==='provider'?'selected':''} onClick={()=>{setRole('provider');setView('home')}}>Professional</button></div><button className="icon-btn"><Bell size={19}/><span className="dot"/></button><button className="avatar" onClick={()=>setView('profile')}>M</button></div>
    </header>
    <main>
      {role==='customer' ? <>
        {view==='home'&&<CustomerHome jobs={filteredJobs} query={query} setQuery={setQuery} onPost={()=>setShowPost(true)} onOpen={setSelectedJob}/>} 
        {view==='jobs'&&<JobsView jobs={jobs} onOpen={setSelectedJob} onPost={()=>setShowPost(true)}/>} 
      </> : <>{(view==='home'||view==='jobs')&&<ProviderDashboard jobs={filteredJobs} bids={bids} query={query} setQuery={setQuery} onOpen={setSelectedJob}/>}</>}
      {view==='messages'&&<MessagesView/>}{view==='profile'&&<ProfileView role={role}/>} 
    </main>
    <nav className="mobile-nav"><button onClick={()=>setView('home')} className={view==='home'?'active':''}><Home/><span>Home</span></button><button onClick={()=>setView('jobs')} className={view==='jobs'?'active':''}><BriefcaseBusiness/><span>Jobs</span></button>{role==='customer'&&<button className="mobile-post" onClick={()=>setShowPost(true)}><Plus/></button>}<button onClick={()=>setView('messages')} className={view==='messages'?'active':''}><MessageCircle/><span>Messages</span></button><button onClick={()=>setView('profile')} className={view==='profile'?'active':''}><UserRound/><span>Profile</span></button></nav>
    {showPost&&<PostJobModal onClose={()=>setShowPost(false)} onCreate={createJob}/>} 
    {selectedJob&&<JobModal job={jobs.find(j=>j.id===selectedJob.id)||selectedJob} bids={bids.filter(b=>b.jobId===selectedJob.id)} role={role} onClose={()=>setSelectedJob(null)} onAccept={acceptBid} onBid={submitBid} onAdvance={advanceJob} notify={notify}/>} 
    {toast&&<div className="toast"><CheckCircle2 size={19}/>{toast}</div>}
  </div>;
}

function CustomerHome({jobs,query,setQuery,onPost,onOpen}:{jobs:Job[];query:string;setQuery:(s:string)=>void;onPost:()=>void;onOpen:(j:Job)=>void}){
 return <><section className="hero"><div className="hero-copy"><span className="eyebrow"><WandSparkles size={16}/> AI-powered service requests</span><h1>Tell us the problem. <em>We handle the complexity.</em></h1><p>Khidmati structures your request, estimates a fair range, finds the best professionals, compares bids, and protects the job until completion.</p><div className="hero-actions"><button className="primary" onClick={onPost}><Plus size={19}/> Ask Khidmati AI</button><button className="secondary" onClick={()=>document.getElementById('open-jobs')?.scrollIntoView()}><Search size={18}/> Browse services</button></div><div className="trust-row"><span><strong>AI</strong> guided diagnosis</span><span><strong>Verified</strong> professionals</span><span><strong>Protected</strong> scope & payment</span></div></div>
 <div className="hero-card ai-hero"><div className="job-preview-head"><div className="status-pill"><Bot size={14}/> AI analysis</div><span>Ready to publish</span></div><h3>“My AC clicks and does not cool.”</h3><div className="analysis-grid"><span><small>Category</small><b>AC & Cooling</b></span><span><small>Urgency</small><b>Medium</b></span><span><small>Fair range</small><b>JOD 25–70</b></span><span><small>Duration</small><b>30–90 min</b></span></div><div className="ai-note"><Sparkles size={18}/><p>Likely fan, capacitor, relay, filter, or refrigerant issue. One follow-up question can improve quote accuracy.</p></div><button className="full-btn" onClick={onPost}>Start AI request <ChevronRight size={17}/></button></div></section>
 <section className="section-wrap"><div className="section-heading"><div><span className="eyebrow">Popular services</span><h2>What do you need help with?</h2></div></div><div className="category-grid">{categories.map(({name,icon:Icon})=><button key={name} className="category-card" onClick={onPost}><span><Icon/></span><strong>{name}</strong><small>Get matched</small></button>)}</div></section>
 <section className="how-section"><span className="eyebrow">AI + human trust</span><h2>A complete marketplace flow</h2><div className="steps"><Step n="01" title="Describe naturally" text="Use text, voice, photos, or video."/><Step n="02" title="AI structures it" text="Category, urgency, range, and questions."/><Step n="03" title="Compare bids" text="See price, scope, ETA, warranty, and AI ranking."/><Step n="04" title="Complete safely" text="Track scope, evidence, confirmation, and reviews."/></div></section>
 <section id="open-jobs" className="section-wrap"><div className="section-heading"><div><span className="eyebrow">Marketplace activity</span><h2>Current requests</h2></div><div className="search-small"><Search size={17}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search requests"/></div></div><div className="job-grid">{jobs.map(j=><JobCard key={j.id} job={j} onOpen={onOpen}/>)}</div></section></>;
}

function ProviderDashboard({jobs,bids,query,setQuery,onOpen}:{jobs:Job[];bids:Bid[];query:string;setQuery:(s:string)=>void;onOpen:(j:Job)=>void}){
 return <div className="dashboard-wrap"><div className="dashboard-title"><div><span className="eyebrow"><Bot size={15}/> Professional AI workspace</span><h1>Win better jobs, faster.</h1><p>Matched by skill and location, with AI-generated bid support.</p></div></div><div className="stats-grid"><Stat label="Matching jobs" value={String(jobs.filter(j=>j.status==='Open').length)} note="In your service area"/><Stat label="Active bids" value={String(bids.filter(b=>b.provider==='Mohammad Services').length)} note="Submitted by you"/><Stat label="Profile score" value="91%" note="Strong trust profile"/><Stat label="Completion rate" value="98%" note="Top professional tier"/></div><div className="provider-toolbar"><div className="search-large"><Search/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search matching jobs"/></div><button className="secondary"><Sparkles size={17}/> Improve profile</button></div><div className="job-grid">{jobs.map(j=><JobCard key={j.id} job={j} onOpen={onOpen} provider/>)}</div></div>;
}

function JobsView({jobs,onOpen,onPost}:{jobs:Job[];onOpen:(j:Job)=>void;onPost:()=>void}){return <div className="dashboard-wrap"><div className="dashboard-title"><div><span className="eyebrow">My requests</span><h1>Manage every job in one place</h1></div><button className="primary" onClick={onPost}><Plus size={18}/> New request</button></div><div className="status-summary">{(['Open','Booked','On the way','In progress','Awaiting confirmation','Completed'] as JobStatus[]).map(s=><div key={s}><span>{s}</span><b>{jobs.filter(j=>j.status===s).length}</b></div>)}</div><div className="job-list">{jobs.map(j=><JobCard key={j.id} job={j} onOpen={onOpen} horizontal/>)}</div></div>}

function JobCard({job,onOpen,horizontal=false,provider=false}:{job:Job;onOpen:(j:Job)=>void;horizontal?:boolean;provider?:boolean}){return <article className={`job-card ${horizontal?'horizontal':''}`} onClick={()=>onOpen(job)}><div className="job-card-top"><span className="category-tag">{job.category}</span><span className={`status status-${job.status.toLowerCase().replace(/\s+/g,'-')}`}>{job.status}</span></div><h3>{job.title}</h3><p>{job.description}</p><div className="job-meta"><span><MapPin size={15}/>{job.location}</span><span><Clock3 size={15}/>{job.timing}</span></div><div className="ai-mini"><Bot size={16}/><span>{job.ai.urgency} urgency · {job.ai.duration} · {job.ai.range}</span></div><div className="job-footer"><div><small>Budget</small><strong>{job.budget}</strong></div><div><small>{provider?'Skill match':'Created'}</small><strong>{provider?'Strong':job.createdAt}</strong></div><button className="round-arrow"><ChevronRight/></button></div></article>}

function PostJobModal({onClose,onCreate}:{onClose:()=>void;onCreate:(j:Omit<Job,'id'|'status'|'createdAt'|'ai'>&{ai:AiAnalysis})=>void}){
 const [step,setStep]=useState(1); const [form,setForm]=useState({title:'',description:'',location:'Amman, Jordan',timing:'Today',budget:'Open to bids'}); const [analysis,setAnalysis]=useState<AiAnalysis|null>(null);
 const runAI=()=>{if(form.description.trim().length<8)return;setAnalysis(analyzeRequest(form.description,form.title));setStep(2)};
 const publish=()=>analysis&&onCreate({...form,category:analysis.category,ai:analysis});
 return <div className="modal-backdrop"><div className="modal large"><div className="modal-head"><div><span className="eyebrow"><Bot size={15}/> AI request assistant</span><h2>{step===1?'Describe the problem':step===2?'Review AI analysis':'Location and publishing'}</h2></div><button className="icon-btn" onClick={onClose}><X/></button></div><div className="stepbar"><span className={step>=1?'active':''}/><span className={step>=2?'active':''}/><span className={step>=3?'active':''}/></div>
 {step===1&&<div className="form-body"><label>Short title<input value={form.title} onChange={e=>setForm({...form,title:e.target.value})} placeholder="Example: AC is clicking and not cooling"/></label><label>Tell Khidmati what happened<textarea value={form.description} onChange={e=>setForm({...form,description:e.target.value})} placeholder="Describe it naturally. Mention noises, leaks, timing, or anything you noticed."/></label><button className="upload-box"><Plus/>Add photos, video, or voice note<small>MVP demo: media upload connects when backend storage is configured.</small></button><div className="privacy-note"><ShieldCheck/><p>Do not include your exact home address. It is only shared after you accept a bid.</p></div></div>}
 {step===2&&analysis&&<div className="form-body"><div className="ai-analysis"><div className="ai-title"><WandSparkles/><div><strong>Khidmati AI analysis</strong><span>Review and correct before publishing</span></div></div><div className="analysis-grid"><span><small>Category</small><b>{analysis.category}</b></span><span><small>Urgency</small><b>{analysis.urgency}</b></span><span><small>Fair range</small><b>{analysis.range}</b></span><span><small>Duration</small><b>{analysis.duration}</b></span></div><p>{analysis.summary}</p><div className="warning"><ShieldCheck/><span>{analysis.risk}</span></div></div><h3>Helpful follow-up questions</h3>{analysis.questions.map(q=><label key={q}>{q}<input placeholder="Optional answer"/></label>)}</div>}
 {step===3&&analysis&&<div className="form-body two-col"><label>General location<input value={form.location} onChange={e=>setForm({...form,location:e.target.value})}/></label><label>Preferred timing<select value={form.timing} onChange={e=>setForm({...form,timing:e.target.value})}><option>Today</option><option>Tomorrow</option><option>This week</option><option>Flexible</option></select></label><label>Budget preference<select value={form.budget} onChange={e=>setForm({...form,budget:e.target.value})}><option>Open to bids</option><option>{analysis.range}</option><option>Under JOD 25</option><option>JOD 25–50</option><option>JOD 50–100</option><option>JOD 100+</option></select></label><div className="publish-summary"><span className="category-tag">{analysis.category}</span><h3>{form.title||'Service request'}</h3><p>{form.description}</p></div></div>}
 <div className="modal-footer"><button className="secondary" onClick={()=>step===1?onClose():setStep(step-1)}>{step===1?'Cancel':'Back'}</button>{step===1?<button className="primary" disabled={!form.title.trim()||form.description.trim().length<8} onClick={runAI}><Sparkles size={17}/> Analyze request</button>:step===2?<button className="primary" onClick={()=>setStep(3)}>Continue <ChevronRight size={17}/></button>:<button className="primary" onClick={publish}>Publish request <Check size={17}/></button>}</div></div></div>;
}

function JobModal({job,bids,role,onClose,onAccept,onBid,onAdvance,notify}:{job:Job;bids:Bid[];role:Role;onClose:()=>void;onAccept:(j:number,b:number)=>void;onBid:(j:number,b:Omit<Bid,'id'|'jobId'>)=>void;onAdvance:(j:number)=>void;notify:(s:string)=>void}){
 const [tab,setTab]=useState<'details'|'bids'|'activity'>('details'); const [price,setPrice]=useState('40'); const [message,setMessage]=useState('I can inspect and complete this job. The price includes diagnosis and minor repair labor. Any parts will be approved first.');
 const ranked=[...bids].sort((a,b)=>score(b)-score(a)); const accepted=bids.find(b=>b.id===job.acceptedBidId);
 function score(b:Bid){return b.rating*20+b.completionRate-b.price*.25+(b.verified?12:0)}
 return <div className="modal-backdrop"><div className="modal job-detail"><div className="modal-head"><div><span className="category-tag">{job.category}</span><h2>{job.title}</h2></div><button className="icon-btn" onClick={onClose}><X/></button></div><div className="detail-summary"><span><MapPin/>{job.location}</span><span><Clock3/>{job.timing}</span><span><UsersRound/>{bids.length} bids</span><strong>{job.status}</strong></div><div className="tabs"><button className={tab==='details'?'active':''} onClick={()=>setTab('details')}>Details</button><button className={tab==='bids'?'active':''} onClick={()=>setTab('bids')}>Bids ({bids.length})</button><button className={tab==='activity'?'active':''} onClick={()=>setTab('activity')}>Job activity</button></div>
 {tab==='details'&&<div className="form-body"><div className="ai-analysis compact"><div className="ai-title"><Bot/><div><strong>AI service brief</strong><span>{job.ai.urgency} urgency · {job.ai.range}</span></div></div><p>{job.ai.summary}</p><div className="warning"><ShieldCheck/><span>{job.ai.risk}</span></div></div><h3>Customer description</h3><p>{job.description}</p>{role==='provider'&&job.status==='Open'&&<div className="bid-form"><div className="ai-title"><Sparkles/><div><strong>AI-assisted bid</strong><span>Edit before sending</span></div></div><div className="two-col"><label>Your price (JOD)<input type="number" min="1" value={price} onChange={e=>setPrice(e.target.value)}/></label><label>Arrival<select><option>Within 1 hour</option><option>Today</option><option>Tomorrow</option></select></label></div><label>Scope and conditions<textarea value={message} onChange={e=>setMessage(e.target.value)}/></label><button className="primary full-width" onClick={()=>{onBid(job.id,{provider:'Mohammad Services',profession:'Verified Professional',rating:4.9,reviews:24,price:Number(price)||40,arrival:'Today',warranty:'30 days',message,verified:true,completionRate:98});setTab('bids')}}>Submit bid</button></div>}</div>}
 {tab==='bids'&&<div className="bid-list">{ranked.length===0?<div className="empty-state"><UsersRound/><h3>No bids yet</h3><p>Matched professionals will appear here.</p></div>:<><div className="ai-recommendation"><Sparkles/><div><strong>AI recommendation</strong><p>{ranked[0].provider} currently offers the strongest balance of verified trust, rating, completion rate, scope, and price.</p></div></div>{ranked.map((b,i)=><div className={`bid-card ${job.acceptedBidId===b.id?'accepted':''}`} key={b.id}><div className="rank-badge">#{i+1}</div><div className="bid-provider"><div className="provider-avatar">{b.provider[0]}</div><div><strong>{b.provider}{b.verified&&<BadgeCheck size={16}/>}</strong><span>{b.profession}</span><small><Star size={14} fill="currentColor"/>{b.rating} · {b.reviews} reviews · {b.completionRate}% completed</small></div></div><div className="bid-price"><strong>JOD {b.price}</strong><span>{b.arrival}</span><small>{b.warranty} warranty</small></div><p>{b.message}</p>{role==='customer'&&job.status==='Open'&&<div className="bid-actions"><button className="secondary" onClick={()=>notify('Conversation opened.')}>Message</button><button className="primary" onClick={()=>onAccept(job.id,b.id)}>Accept bid</button></div>}{job.acceptedBidId===b.id&&<div className="accepted-label"><CheckCircle2/> Accepted professional</div>}</div>)}</>}</div>}
 {tab==='activity'&&<div className="form-body"><div className="job-progress">{(['Booked','On the way','In progress','Awaiting confirmation','Completed'] as JobStatus[]).map((s,i)=>{const current=['Booked','On the way','In progress','Awaiting confirmation','Completed'].indexOf(job.status);return <div className={i<=current?'complete':''} key={s}><span>{i<=current?<Check/>:i+1}</span><b>{s}</b></div>})}</div>{accepted&&<div className="accepted-provider"><div className="provider-avatar">{accepted.provider[0]}</div><div><strong>{accepted.provider}</strong><span>{accepted.profession} · JOD {accepted.price}</span></div></div>}<div className="ai-note"><Bot/><p>AI job record: agreed scope, bid, messages, approved changes, evidence, and final confirmation remain attached to this job.</p></div>{job.status!=='Open'&&job.status!=='Completed'&&<button className="primary full-width" onClick={()=>onAdvance(job.id)}>{role==='provider'?'Update job status':'Confirm next step'} <ChevronRight/></button>}{job.status==='Completed'&&<ReviewPanel notify={notify}/>}</div>}
 </div></div>;
}

function ReviewPanel({notify}:{notify:(s:string)=>void}){const [rating,setRating]=useState(0);return <div className="review-panel"><h3>Complete your mutual review</h3><p>Reviews are published after both parties submit or when the review period closes.</p><div className="stars-input">{[1,2,3,4,5].map(n=><button key={n} onClick={()=>setRating(n)}><Star fill={n<=rating?'currentColor':'none'}/></button>)}</div><textarea placeholder="Share clear, factual feedback."/><button className="primary" disabled={!rating} onClick={()=>notify('Review submitted privately.')}>Submit review</button></div>}

function MessagesView(){const [messages,setMessages]=useState<Message[]>([{id:1,from:'other',text:'I reviewed the request. Is the leak from the pipe joint or the drain?',time:'10:39'},{id:2,from:'me',text:'It appears to be from the pipe joint under the sink.',time:'10:41'},{id:3,from:'other',text:'Understood. I will bring common fittings and can arrive within one hour.',time:'10:42'}]);const [text,setText]=useState('');const send=()=>{if(!text.trim())return;setMessages(x=>[...x,{id:Date.now(),from:'me',text:text.trim(),time:'Now'}]);setText('')};return <div className="dashboard-wrap"><div className="dashboard-title"><div><span className="eyebrow">Messages</span><h1>Job conversations</h1></div></div><div className="messages-shell"><div className="conversation-list"><div className="conversation active"><div className="mini-avatar">A</div><div><strong>Ahmad Al-Khatib</strong><p>Kitchen sink is leaking</p></div><span>Now</span></div><div className="conversation"><div className="mini-avatar">S</div><div><strong>Sami HVAC</strong><p>AC inspection</p></div><span>Yesterday</span></div></div><div className="chat-panel"><div className="chat-head"><div className="mini-avatar">A</div><div><strong>Ahmad Al-Khatib</strong><span>Verified · Online</span></div></div><div className="chat-ai"><Bot/><span>AI scope summary: diagnosis and minor fitting replacement included. Major parts require approval.</span></div><div className="chat-body">{messages.map(m=><div key={m.id} className={`bubble ${m.from==='me'?'me':'other'}`}>{m.text}<small>{m.time}</small></div>)}</div><div className="chat-input"><input value={text} onChange={e=>setText(e.target.value)} onKeyDown={e=>e.key==='Enter'&&send()} placeholder="Write a message..."/><button onClick={send}><ChevronRight/></button></div></div></div></div>}

function ProfileView({role}:{role:Role}){return <div className="dashboard-wrap"><div className="profile-header"><div className="large-avatar">M</div><div><span className="eyebrow">{role==='provider'?'Professional profile':'Customer profile'}</span><h1>Mohammad Abu-Dalhoum</h1><p><MapPin size={15}/> Amman, Jordan · Member since 2026</p><div className="rating-line"><Star size={17} fill="currentColor"/><strong>4.9</strong><span>24 reviews</span></div></div><button className="secondary">Edit profile</button></div><div className="profile-grid"><section className="panel"><h3>Trust profile</h3><Verification icon={<BadgeCheck/>} title="Identity verified" text="Government ID and phone confirmed"/><Verification icon={<ShieldCheck/>} title="No unresolved disputes" text="Strong transaction history"/>{role==='provider'&&<><Verification icon={<Wrench/>} title="Skills verified" text="HVAC and general maintenance"/><Verification icon={<CircleDollarSign/>} title="Payout verified" text="Payment account confirmed"/></>}</section><section className="panel"><h3>Performance</h3><div className="profile-metrics"><div><b>98%</b><span>Completion</span></div><div><b>12 min</b><span>Response</span></div><div><b>37%</b><span>Repeat clients</span></div><div><b>4.9</b><span>Rating</span></div></div><h3>Recent reviews</h3><Review name="Ahmad Al-Khatib" text="Clear communication and the job matched the description."/><Review name="Omar Maintenance" text="Respectful, organized, and quick to confirm completion."/></section></div></div>}

function Verification({icon,title,text}:{icon:React.ReactNode;title:string;text:string}){return <div className="verification">{icon}<div><strong>{title}</strong><span>{text}</span></div></div>}
function Step({n,title,text}:{n:string;title:string;text:string}){return <div className="step"><span>{n}</span><h3>{title}</h3><p>{text}</p></div>}
function Stat({label,value,note}:{label:string;value:string;note:string}){return <div className="stat"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>}
function Review({name,text}:{name:string;text:string}){return <div className="review"><div className="review-head"><strong>{name}</strong><span><Star size={14} fill="currentColor"/>5.0</span></div><p>{text}</p></div>}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
