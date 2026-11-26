import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiBlob } from "../api/client";
import { initials } from "../lib/format";

/** Profile pictures are private (signed-in only), so they are fetched with the token and shown from memory. */
export function Avatar({ url, name, size = 36 }: { url: string | null | undefined; name: string | null | undefined; size?: number }) {
  const blob = useQuery({ queryKey: ["avatar", url], queryFn: () => apiBlob(url!), enabled: !!url, staleTime: Infinity, retry: false });
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!blob.data) return setSrc(null);
    const objectUrl = URL.createObjectURL(blob.data);
    setSrc(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [blob.data]);
  const style = { width: size, height: size, fontSize: Math.round(size * 0.36) };
  return src ? (
    <img className="avatar" src={src} alt="" style={style} />
  ) : (
    <span className="avatar avatar-initials" style={style} aria-hidden="true">
      {initials(name)}
    </span>
  );
}
