"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, ChevronDown, ChevronRight, Download, Pause, Play, Radio, RefreshCw } from "lucide-react";

type WorkEvent = {
  id: string; sourceId: string; sourceName: string; receivedAt: string;
  jobId?: string; format: string; height?: number; previousBlockHash?: string;
  transactionCount?: number; coinbaseValueSats?: number; merkleBranches?: string[];
  cleanJobs?: boolean; powAlgorithm?: string; publishedAt?: string;
  [key: string]: unknown;
};
type Source = {
  id: string; name: string; url: string; activeUrl?: string; powAlgorithm?: string; kind: string; status: string;
  lastSeen?: string | null; error?: string | null; latest?: WorkEvent | null;
};
type Snapshot = { generatedAt: string; sources: Source[]; events: WorkEvent[] };

const sourceLinks: Record<string, string> = {
  alpha: "https://knots.alphapool.tech", pyblock: "https://b.pyblock.xyz:8443/",
  xor: "https://xorpool.com/connect",
};
const short = (value?: string) => value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "Not supplied";
const time = (value?: string | null) => value ? new Date(value).toLocaleTimeString([], { hour12: false }) : "—";
const formatName = (value?: string) => ({ "datum-template": "Full template", "bitcoin-stratum-v1": "Stratum job", "sia-stratum": "Sia work", "unknown-stratum": "Raw work" }[value || ""] || "Awaiting work");
const isConnected = (status: string) => ["connected", "live", "ok"].includes(status);

export default function DatumWork() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [sourceFilter, setSourceFilter] = useState("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (paused) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch("/api/datum/snapshot", { cache: "no-store", signal: controller.signal });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Unable to reach the monitor");
        if (!Array.isArray(data.sources) || !Array.isArray(data.events)) throw new Error("Invalid monitor response");
        setSnapshot(data); setError(null);
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Unable to reach the monitor");
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [paused, refresh]);

  const sources = snapshot?.sources || [];
  const events = (snapshot?.events || []).filter(event => sourceFilter === "all" || event.sourceId === sourceFilter);
  const online = sources.filter(source => isConnected(source.status)).length;
  const own = sources.find(source => source.id === "own")?.latest;
  const download = () => {
    if (!snapshot) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "datum-work-snapshot.json"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <main className="min-h-screen bg-[#101110] text-[#ededdf] font-mono selection:bg-[#edaa56] selection:text-black">
      <header className="border-b border-white/10 px-5 md:px-10">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-4 py-5">
          <Link href="/" aria-label="Datum Work home" className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#edaa56] text-xl font-bold text-[#101110]">d.</span>
            <span className="text-xl font-semibold tracking-tight">datum<span className="text-[#edaa56]">.work</span></span>
          </Link>
          <div className="flex items-center gap-5 text-xs text-[#a4a99d]">
            <span className="hidden sm:inline">POOL & TEMPLATE OBSERVATORY</span>
            <a href="https://github.com/f4u57ox/datum-work" target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 hover:text-white">Source <ArrowUpRight size={14}/></a>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1600px] px-5 py-8 md:px-10 md:py-10">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="mb-3 text-xs tracking-[0.18em] text-[#edaa56]">WATCH THE WORK</p>
            <h1 className="text-3xl font-medium tracking-tight md:text-4xl">Every pool. Your templates.</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[#a4a99d]">Follow new mining jobs and inspect the block templates your DATUM gateway publishes.</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setPaused(!paused)} className="flex items-center gap-2 rounded-md border border-white/15 px-3 py-2 text-xs hover:bg-white/5">{paused ? <Play size={14}/> : <Pause size={14}/>} {paused ? "Resume" : "Pause view"}</button>
            <button disabled={paused} onClick={() => setRefresh(value => value + 1)} aria-label="Refresh monitor" title="Refresh monitor" className="rounded-md border border-white/15 p-2 hover:bg-white/5 disabled:opacity-30"><RefreshCw size={16}/></button>
          </div>
        </div>

        <div role="status" className="mb-6 flex flex-wrap items-center gap-x-7 gap-y-2 border-y border-white/10 py-4 text-xs">
          <span className={`flex items-center gap-2 ${paused || error ? "text-[#edaa56]" : "text-[#afd2a1]"}`}><Radio size={14}/>{paused ? "VIEW PAUSED · collector continues" : error ? "MONITOR OFFLINE" : snapshot ? "UPDATING EVERY 3s" : "CONNECTING TO MONITOR"}</span>
          <span className="text-[#a4a99d]">Sources <span className="text-white">{error ? "—" : `${online}/${sources.length || "—"}`}</span></span>
          <span className="text-[#a4a99d]">Own height <span className="text-white">{own?.height?.toLocaleString() || "—"}</span></span>
          <span className="text-[#a4a99d]">Snapshot <span className="text-white" suppressHydrationWarning>{time(snapshot?.generatedAt)}</span></span>
        </div>

        {error && <div role="alert" className="mb-6 rounded-md border border-[#edaa56]/30 bg-[#edaa56]/5 p-4 text-sm text-[#edaa56]">{error}{snapshot && <span className="block mt-2 text-xs">Showing the last received snapshot. Source states below are historical.</span>}</div>}

        <section aria-label="Monitored sources" className="mb-9 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {sources.map(source => {
            const latest = source.latest;
            const connected = isConnected(source.status) && !error;
            return <article key={source.id} className={`min-w-0 rounded-lg border p-5 ${source.id === "own" ? "border-[#edaa56]/40 bg-[#edaa56]/[0.035]" : "border-white/10 bg-[#171916]"}`}>
              <div className="mb-5 flex items-center justify-between gap-2">
                <h2 className="font-semibold text-sm">{source.name}</h2>
                <span className={`flex items-center gap-1.5 text-[10px] uppercase ${connected ? "text-[#afd2a1]" : "text-[#a4a99d]"}`}><span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-[#afd2a1]" : "bg-[#a4a99d]"}`}/>{error ? "cached" : source.status}</span>
              </div>
              <p className="text-[10px] uppercase tracking-wider text-[#929889]">{latest?.height != null ? "Template height" : "Latest job"}</p>
              <p className="mt-2 truncate text-2xl tracking-tight" title={latest?.jobId}>{latest?.height != null ? latest.height.toLocaleString() : latest?.jobId || "—"}</p>
              <div className="mt-4 flex flex-wrap gap-2 text-[10px]">
                <span className="rounded bg-white/5 px-2 py-1 text-[#c5caba]">{formatName(latest?.format)}</span>
                {(latest?.powAlgorithm || source.powAlgorithm) && <span className="rounded bg-white/5 px-2 py-1 uppercase text-[#c5caba]">{latest?.powAlgorithm || source.powAlgorithm}</span>}
              </div>
              <p className="mt-4 break-all text-[10px] leading-5 text-[#929889]">{source.activeUrl || source.url}</p>
              <p className="mt-1 text-[10px] text-[#929889]">Last work {time(source.lastSeen)}</p>
              {source.error && <p className="mt-3 break-words text-[11px] leading-5 text-[#edaa56]">{source.error}</p>}
              {sourceLinks[source.id] && <a className="mt-3 inline-flex items-center gap-1 text-[10px] text-[#a4a99d] hover:text-white" href={sourceLinks[source.id]} target="_blank" rel="noopener noreferrer">Pool connection guide <ArrowUpRight size={11}/></a>}
            </article>;
          })}
          {!sources.length && <div className="col-span-full rounded-lg border border-dashed border-white/15 px-6 py-10 text-center text-sm text-[#a4a99d]">{error ? "Waiting for the monitor service. No pool data has been received." : "Loading the configured pool and DATUM sources…"}</div>}
        </section>

        <section aria-label="Work event stream" className="overflow-hidden rounded-lg border border-white/10">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 bg-[#171916] px-5 py-4">
            <div className="flex items-center gap-3"><h2 className="text-sm font-semibold">Work stream</h2><span className="rounded-full bg-white/5 px-2 py-0.5 text-[10px] text-[#a4a99d]">{events.length} events</span></div>
            <div className="flex items-center gap-3">
              <label className="sr-only" htmlFor="source-filter">Filter source</label>
              <select id="source-filter" value={sourceFilter} onChange={event => setSourceFilter(event.target.value)} className="rounded border border-white/15 bg-[#171916] px-2 py-1.5 text-xs"><option value="all">All sources</option>{sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select>
              <button onClick={download} disabled={!snapshot} title="Download observed work as JSON" className="flex items-center gap-1.5 text-xs text-[#a4a99d] hover:text-white disabled:opacity-30"><Download size={14}/><span className="hidden sm:inline">Export</span></button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full whitespace-nowrap text-left text-xs">
              <thead className="bg-[#141613] text-[10px] uppercase tracking-wider text-[#929889]"><tr>{["", "Received", "Source / work", "Job", "Height", "Previous block", "Txs", "Clean"].map((heading, index) => <th key={index} scope="col" className="px-4 py-3 font-normal">{heading}</th>)}</tr></thead>
              <tbody>
                {events.map(event => <Fragment key={event.id}>
                  <tr className={`border-t border-white/5 hover:bg-white/[0.025] ${event.sourceId === "own" ? "bg-[#edaa56]/[0.025]" : ""}`}>
                    <td className="py-3 pl-4"><button aria-label={`${expanded === event.id ? "Hide" : "Inspect"} job ${event.jobId || event.id}`} aria-expanded={expanded === event.id} onClick={() => setExpanded(expanded === event.id ? null : event.id)} className="p-1 text-[#a4a99d]">{expanded === event.id ? <ChevronDown size={15}/> : <ChevronRight size={15}/>}</button></td>
                    <td className="px-4 py-3 text-[#a4a99d]">{time(event.receivedAt)}</td>
                    <td className="px-4 py-3"><span className={event.sourceId === "own" ? "text-[#edaa56]" : ""}>{event.sourceName}</span><span className="mt-1 block text-[10px] text-[#929889]">{formatName(event.format)} · {event.powAlgorithm || "unspecified"}</span></td>
                    <td className="max-w-[170px] truncate px-4 py-3" title={event.jobId}>{event.jobId || "—"}</td>
                    <td className="px-4 py-3">{event.height?.toLocaleString() || "—"}</td>
                    <td className="px-4 py-3 text-[#a4a99d]" title={event.previousBlockHash}>{short(event.previousBlockHash)}</td>
                    <td className="px-4 py-3">{event.transactionCount?.toLocaleString() ?? "—"}</td>
                    <td className="px-4 py-3 text-[#a4a99d]">{event.cleanJobs == null ? "—" : event.cleanJobs ? "Yes" : "No"}</td>
                  </tr>
                  {expanded === event.id && <tr className="border-t border-white/5 bg-black/20"><td colSpan={8} className="p-5"><p className="mb-3 text-xs text-[#edaa56]">Observed work · {formatName(event.format)}</p><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-[11px] leading-5 text-[#bcc5b3]">{JSON.stringify(event, null, 2)}</pre></td></tr>}
                </Fragment>)}
                {!events.length && <tr><td colSpan={8} className="px-5 py-14 text-center text-[#929889]">No work received{sourceFilter !== "all" ? " from this source" : " yet"}. Connection and authorization status appear above.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="border-t border-white/10 px-5 py-3 text-[10px] leading-5 text-[#929889]">Pool work can omit the full block template. Missing heights, transactions and coinbases stay empty. Times are observer receipt times; they do not measure pool latency.</div>
        </section>
        <footer className="mt-8 flex flex-wrap justify-between gap-3 text-[10px] leading-5 text-[#929889]"><p>Datum Work · Built on <a href="https://github.com/bboerst/stratum-work" className="underline hover:text-white">Stratum Work</a></p><Link href="/table" className="inline-flex items-center gap-1 hover:text-white">Original Stratum views <ArrowUpRight size={11}/></Link></footer>
      </div>
    </main>
  );
}
