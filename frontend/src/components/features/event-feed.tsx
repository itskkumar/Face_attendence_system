"use client";
import { AnimatePresence, motion } from "framer-motion";
import { Activity } from "lucide-react";
import { EmptyState } from "@/components/ui/glass";
import { EVENT_LABELS, eventColor } from "@/lib/status";
import type { LiveEvent } from "@/lib/types";
import { fmtPct } from "@/lib/utils";

export function EventFeed({ events, limit = 30, filter }: { events: LiveEvent[]; limit?: number; filter?: (e: LiveEvent) => boolean }) {
  const list = (filter ? events.filter(filter) : events).slice(0, limit);
  if (list.length === 0) return <EmptyState icon={<Activity className="h-5 w-5" />} title="No events yet" description="Events appear here live as people pass the gate." />;
  return (
    <ul className="space-y-1.5" aria-live="polite">
      <AnimatePresence initial={false}>
        {list.map((e) => (
          <motion.li key={e.event_id} layout initial={{ opacity: 0, x: -16 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }}
            className="flex items-start gap-3 rounded-xl border border-[var(--glass-border)] px-3 py-2 text-sm">
            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: eventColor(e.type) }} />
            <div className="min-w-0 flex-1">
              <p className="font-medium">{EVENT_LABELS[e.type] ?? e.type}{e.student ? ` - ${e.student.name} (${e.student.roll_number})` : ""}</p>
              <p className="truncate text-xs text-muted">
                {new Date(e.ts).toLocaleTimeString()} | {e.camera_id} | track {e.track_id}
                {e.pad_real_prob !== null && e.pad_real_prob !== undefined ? ` | real ${fmtPct(e.pad_real_prob)}` : ""}
                {e.similarity !== undefined ? ` | sim ${e.similarity.toFixed(2)}` : ""}
                {e.reason ? ` | ${e.reason}` : ""}
              </p>
            </div>
          </motion.li>
        ))}
      </AnimatePresence>
    </ul>
  );
}
