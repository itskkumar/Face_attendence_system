"use client";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";

type Variant = "success" | "error" | "info" | "warning";
interface ToastItem { id: number; title: string; description?: string; variant: Variant }
interface ToastApi { toast: (t: { title: string; description?: string; variant?: Variant }) => void }

const Ctx = createContext<ToastApi>({ toast: () => undefined });
const ICONS = { success: CheckCircle2, error: XCircle, info: Info, warning: AlertTriangle };
const COLORS: Record<Variant, string> = { success: "#22c55e", error: "#ef4444", info: "#3b82f6", warning: "#eab308" };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const toast = useCallback<ToastApi["toast"]>(({ title, description, variant = "info" }) => {
    const id = nextId.current++;
    setItems((p) => [...p, { id, title, description, variant }].slice(-4));
    setTimeout(() => setItems((p) => p.filter((t) => t.id !== id)), variant === "error" ? 7000 : 4000);
  }, []);
  const value = useMemo(() => ({ toast }), [toast]);
  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(92vw,22rem)] flex-col gap-2" aria-live="polite">
        <AnimatePresence>
          {items.map((t) => {
            const Icon = ICONS[t.variant];
            return (
              <motion.div key={t.id} layout initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40 }}
                className="glass glass-strong pointer-events-auto flex gap-3 rounded-xl p-3" role={t.variant === "error" ? "alert" : "status"}>
                <Icon className="mt-0.5 h-5 w-5 shrink-0" style={{ color: COLORS[t.variant] }} aria-hidden />
                <div className="min-w-0"><p className="text-sm font-medium">{t.title}</p>{t.description && <p className="break-words text-xs text-muted">{t.description}</p>}</div>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
