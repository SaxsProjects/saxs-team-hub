import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiBlob } from "../api/client";
import { initials } from "../lib/format";

/** Profile pictures are private (signed-in only), so they are fetched with the token and shown from memory.
 *  Anyone without a picture shows the SaxsProjects logo until they upload one. */
export function Avatar({ url, name, size = 36 }: { url: string | null | undefined; name: string | null | undefined; size?: number }) {
  const blob = useQuery({ queryKey: ["avatar", url], queryFn: () => apiBlob(url!), enabled: !!url, staleTime: Infinity, retry: false });
  const [src, setSrc] = useState<string | null>(null);
  const [logoFailed, setLogoFailed] = useState(false);
  useEffect(() => {
    if (!blob.data) return setSrc(null);
    const objectUrl = URL.createObjectURL(blob.data);
    setSrc(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [blob.data]);
  const style = { width: size, height: size, fontSize: Math.round(size * 0.36) };
  if (src) return <img className="avatar" src={src} alt="" style={style} />;
  // No picture yet: show the company logo until the person adds their own (initials only if it fails to load).
  if (!logoFailed)
    return (
      <span className="avatar avatar-logo" style={style} aria-hidden="true" title={name ?? undefined}>
        <img src="/icons/logo-mark.png" alt="" onError={() => setLogoFailed(true)} />
      </span>
    );
  return (
    <span className="avatar avatar-initials" style={style} aria-hidden="true">
      {initials(name)}
    </span>
  );
}
