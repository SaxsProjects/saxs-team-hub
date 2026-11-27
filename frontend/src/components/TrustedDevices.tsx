import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fingerprint, Laptop, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { api, post } from "../api/client";
import type { PasskeyOptions, TrustedDevice } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { shortDate } from "../lib/format";
import { cancelled, createPasskey, passkeysAvailable, unlockName } from "../lib/passkey";
import { FormError, Skeleton } from "./ui";

/** Settings > Security: the phones and computers that stay signed in, and the fingerprint or face unlock. */
export function TrustedDevices() {
  const { device } = useAuth();
  const queryClient = useQueryClient();
  const [canPasskey, setCanPasskey] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const list = useQuery({ queryKey: ["devices"], queryFn: () => api<TrustedDevice[]>("/api/auth/devices") });

  useEffect(() => {
    void passkeysAvailable().then(setCanPasskey);
  }, []);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["devices"] });
    void queryClient.invalidateQueries({ queryKey: ["device"] });
  };

  const remove = useMutation({
    mutationFn: (id: number) => api<void>(`/api/auth/devices/${id}`, { method: "DELETE" }),
    onSuccess: () => (setNote("Device removed. It will need your password and two-factor code again."), refresh()),
  });

  const addPasskey = useMutation({
    mutationFn: async () => {
      const { challenge_id, options } = await post<PasskeyOptions>("/api/auth/passkeys/options");
      const credential = await createPasskey(options);
      await post("/api/auth/passkeys", { challenge_id, credential });
    },
    onSuccess: () => (setNote(`Done. Next time, unlock with ${unlockName()}.`), refresh()),
    onError: (e) => cancelled(e) && setNote(null),
  });

  const here = list.data?.find((d) => d.this_device);
  return (
    <div className="trusted-devices">
      <p className="setting-title">Trusted devices</p>
      <p className="field-hint">
        These stay signed in and unlock with a passkey or your password, without a two-factor code. A device you haven’t used for 90 days needs a
        full sign-in again.
      </p>
      {list.isPending && <Skeleton h={60} />}
      <FormError error={list.error} />
      {list.data?.length === 0 && <p className="row-sub">No trusted devices. Tick “Keep me signed in” when you sign in on your phone.</p>}
      {!!list.data?.length && (
        <ul className="device-list">
          {list.data.map((d) => (
            <li key={d.id}>
              <span className="icon-tile" aria-hidden="true">
                {/Android|iPhone|iPad|app/i.test(d.name) ? <Smartphone size={16} /> : <Laptop size={16} />}
              </span>
              <span className="device-text">
                <span className="device-name">
                  {d.name}
                  {d.this_device && <span className="chip chip-success">This device</span>}
                </span>
                <span className="row-sub">
                  {d.passkey ? "Passkey · " : ""}Last used {shortDate(d.last_used_at)}
                </span>
              </span>
              <button className="btn btn-secondary btn-sm" disabled={remove.isPending} onClick={() => remove.mutate(d.id)} aria-label={`Remove ${d.name}`}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {device && here && !here.passkey && canPasskey && (
        <button className="btn btn-secondary btn-block" style={{ marginTop: 10 }} disabled={addPasskey.isPending} onClick={() => (setNote(null), addPasskey.mutate())}>
          <Fingerprint size={16} aria-hidden="true" /> {addPasskey.isPending ? "Waiting…" : `Unlock with ${unlockName()} on this device`}
        </button>
      )}
      {!cancelled(addPasskey.error) && <FormError error={addPasskey.error} />}
      <FormError error={remove.error} />
      {note && (
        <p className="success-text" role="status" style={{ marginTop: 8 }}>
          {note}
        </p>
      )}
    </div>
  );
}

const OFFER_KEY = "teamhub.passkeyOfferDismissed";

/** Once, after "Keep me signed in": offer fingerprint, face or Windows Hello unlock on this device. */
export function PasskeyOffer() {
  const { device } = useAuth();
  const queryClient = useQueryClient();
  const [show, setShow] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let dismissed = false;
    try {
      dismissed = localStorage.getItem(OFFER_KEY) === device?.email;
    } catch {
      /* storage blocked: offer anyway */
    }
    if (!device || device.passkey || dismissed) return setShow(false);
    void passkeysAvailable().then(setShow);
  }, [device]);

  if (!show || !device) return null;
  const dismiss = () => {
    try {
      localStorage.setItem(OFFER_KEY, device.email);
    } catch {
      /* ignore */
    }
    setShow(false);
  };
  async function setUp() {
    setBusy(true);
    setError(null);
    try {
      const { challenge_id, options } = await post<PasskeyOptions>("/api/auth/passkeys/options");
      await post("/api/auth/passkeys", { challenge_id, credential: await createPasskey(options) });
      void queryClient.invalidateQueries({ queryKey: ["device"] });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
      dismiss();
    } catch (e) {
      if (!cancelled(e)) setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="passkey-offer card" role="region" aria-label="Faster unlock">
      <Fingerprint size={20} aria-hidden="true" />
      <div>
        <p className="setting-title">Unlock with {unlockName()}?</p>
        <p className="field-hint">Open the Team Hub on this device without typing your password. Your {unlockName()} stays on the device.</p>
        <FormError error={error} />
      </div>
      <div className="passkey-offer-actions">
        <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void setUp()}>
          {busy ? "Waiting…" : "Set up"}
        </button>
        <button className="btn btn-secondary btn-sm" onClick={dismiss}>
          Not now
        </button>
      </div>
    </div>
  );
}
