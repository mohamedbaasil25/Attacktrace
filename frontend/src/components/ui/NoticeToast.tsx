import { AnimatePresence, motion } from "framer-motion";
import { Lock } from "lucide-react";
import { useEffect } from "react";
import { useUi } from "../../store/ui";

const SHOW_MS = 3500;

/** One-line notice under the top bar (e.g. `Demo locked`). */
export function NoticeToast() {
  const notice = useUi((s) => s.notice);
  const clear = useUi((s) => s.clearNotice);
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(clear, SHOW_MS);
    return () => clearTimeout(t);
  }, [notice, clear]);
  return (
    <div className="pointer-events-none fixed left-1/2 top-24 z-10 -translate-x-1/2" role="alert">
      <AnimatePresence>
        {notice && (
          <motion.div
            key={notice.id}
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex items-center gap-2 rounded border border-suspect bg-surface px-3 py-2 font-mono text-xs"
          >
            <Lock size={14} className="text-suspect" aria-hidden />
            {notice.text}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
