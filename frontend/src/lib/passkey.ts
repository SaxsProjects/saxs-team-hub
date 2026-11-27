/**
 * Passkeys: unlock with Face ID, a fingerprint or Windows Hello. The device checks the face, finger or
 * PIN itself; the Team Hub only ever sees a signed answer, never the fingerprint or face.
 *
 * The server sends WebAuthn options as JSON (byte fields in base64url); these helpers turn them into
 * what the browser expects and the result back into JSON.
 */

type Json = Record<string, unknown>;

function fromB64(text: string): ArrayBuffer {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function toB64(buf: ArrayBuffer | null | undefined): string | undefined {
  if (!buf) return undefined;
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

const descriptors = (list: unknown) =>
  ((list as { id: string; type: string; transports?: string[] }[] | undefined) ?? []).map((d) => ({
    ...d,
    id: fromB64(d.id),
    type: "public-key" as const,
  })) as PublicKeyCredentialDescriptor[];

/** True when this browser can use a passkey built into the device (fingerprint, face, Windows Hello). */
export async function passkeysAvailable(): Promise<boolean> {
  try {
    return typeof window.PublicKeyCredential !== "undefined" && (await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable());
  } catch {
    return false;
  }
}

export async function createPasskey(options: Json): Promise<Json> {
  const user = options.user as Json;
  const publicKey = {
    ...options,
    challenge: fromB64(options.challenge as string),
    user: { ...user, id: fromB64(user.id as string) },
    excludeCredentials: descriptors(options.excludeCredentials),
  } as unknown as PublicKeyCredentialCreationOptions;
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (!cred) throw new Error("The passkey wasn't created.");
  const res = cred.response as AuthenticatorAttestationResponse;
  return {
    id: cred.id,
    rawId: toB64(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: toB64(res.clientDataJSON),
      attestationObject: toB64(res.attestationObject),
      transports: typeof res.getTransports === "function" ? res.getTransports() : undefined,
    },
    clientExtensionResults: cred.getClientExtensionResults(),
    authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
  };
}

export async function signWithPasskey(options: Json, signal?: AbortSignal): Promise<Json> {
  const publicKey = {
    ...options,
    challenge: fromB64(options.challenge as string),
    allowCredentials: descriptors(options.allowCredentials),
  } as unknown as PublicKeyCredentialRequestOptions;
  const cred = (await navigator.credentials.get({ publicKey, signal })) as PublicKeyCredential | null;
  if (!cred) throw new Error("No passkey was used.");
  const res = cred.response as AuthenticatorAssertionResponse;
  return {
    id: cred.id,
    rawId: toB64(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: toB64(res.clientDataJSON),
      authenticatorData: toB64(res.authenticatorData),
      signature: toB64(res.signature),
      userHandle: toB64(res.userHandle),
    },
    clientExtensionResults: cred.getClientExtensionResults(),
  };
}

/** A cancelled or timed-out prompt is not an error worth showing: the person chose the password. */
export function cancelled(e: unknown): boolean {
  return e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "AbortError");
}

/** What to call the device's unlock method on screen. */
export function unlockName(): string {
  const ua = navigator.userAgent;
  if (/iPhone|iPad/.test(ua)) return "Face ID or Touch ID";
  if (/Android/.test(ua)) return "fingerprint or face";
  if (/Windows/.test(ua)) return "Windows Hello";
  if (/Mac OS/.test(ua)) return "Touch ID";
  return "passkey";
}
