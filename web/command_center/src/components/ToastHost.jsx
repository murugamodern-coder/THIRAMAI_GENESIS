import { useToastStore } from "../store/useToastStore.js";
import Toast from "./ui/Toast.jsx";

export default function ToastHost() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div className="cc-toast-host" role="region" aria-label="Notifications">
      {(Array.isArray(toasts) ? toasts : []).map((t) => (
        <Toast key={t.id} toast={t} onDismiss={dismiss} />
      ))}
    </div>
  );
}

