export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  try {
    const base = process.env.DATUM_MONITOR_URL || "http://127.0.0.1:8810";
    const response = await fetch(`${base.replace(/\/$/, "")}/api/snapshot`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Monitor unavailable");
    return Response.json(await response.json(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "The Datum monitor is offline. Start the monitor service to receive live work." }, {
      status: 503, headers: { "Cache-Control": "no-store" },
    });
  }
}
