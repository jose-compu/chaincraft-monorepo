/** Peer address book and local-discovery policy.
 *
 * SPEC/features/discovery-peer.md and SPEC/features/discovery-local.md.
 */

export const DEFAULT_CAPACITY = 50;
export const DEFAULT_TIMEOUT_MS = 120_000;

export function isResolvedIpAllowed(ip: string): boolean {
  const labels = ip.split('.');
  if (labels.length !== 4 || !labels.every((label) => /^[0-9]+$/.test(label))) return false;
  const first = labels[0];
  const second = labels[1];
  if (first === undefined || second === undefined) return false;
  const octets = labels.map((label) => Number(label));
  if (octets.some((octet) => !Number.isSafeInteger(octet) || octet > 255)) return false;
  const a = Number(first);
  const b = Number(second);
  if (a === 0 || a >= 224) return false;
  if (a === 169 && b === 254) return false;
  return true;
}

export function isConnectAllowed(address: string): boolean {
  if (!isValidAddress(address)) return false;
  const split = splitHostPort(address);
  if (!split) return false;
  const labels = split.host.split('.');
  if (labels.length === 4 && labels.every((label) => /^[0-9]+$/.test(label))) {
    return isResolvedIpAllowed(split.host);
  }
  return true;
}

export function isValidAddress(address: string): boolean {
  const split = splitHostPort(address);
  if (!split) return false;
  return validHost(split.host) && validPort(split.port);
}

function splitHostPort(address: string): { host: string; port: string } | undefined {
  const idx = address.lastIndexOf(':');
  if (idx <= 0 || idx === address.length - 1) return undefined;
  return { host: address.slice(0, idx), port: address.slice(idx + 1) };
}

function validPort(port: string): boolean {
  if (!/^[0-9]+$/.test(port)) return false;
  if (port.length > 1 && port[0] === '0') return false;
  const value = Number(port);
  return Number.isSafeInteger(value) && value >= 1 && value <= 65535;
}

function validHost(host: string): boolean {
  if (!host || host.length > 253) return false;
  const labels = host.split('.');
  if (labels.length === 4 && labels.every((label) => /^[0-9]+$/.test(label))) {
    return validIpv4(labels);
  }
  return validHostname(labels);
}

function validIpv4(labels: string[]): boolean {
  for (const label of labels) {
    if (label.length > 1 && label[0] === '0') return false;
    const value = Number(label);
    if (!Number.isSafeInteger(value) || value < 0 || value > 255) return false;
  }
  return true;
}

function validHostname(labels: string[]): boolean {
  if (labels.length === 0 || labels[0] === '' || labels[labels.length - 1] === '') {
    return false;
  }
  for (const label of labels) {
    if (label.length < 1 || label.length > 63) return false;
    if (label[0] === '-' || label[label.length - 1] === '-') return false;
    if (!/^[A-Za-z0-9-]+$/.test(label)) return false;
  }
  return true;
}

export class AddressBook {
  readonly listen: string | undefined;
  readonly capacity: number;
  readonly timeoutMs: number;
  private readonly entries = new Map<string, number>();
  private readonly solicited = new Set<string>();

  constructor(
    listen?: string,
    capacity: number = DEFAULT_CAPACITY,
    timeoutMs: number = DEFAULT_TIMEOUT_MS,
  ) {
    if (!Number.isSafeInteger(capacity) || capacity < 1) {
      throw new RangeError('capacity must be a positive integer');
    }
    if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
      throw new RangeError('timeoutMs must be a positive integer');
    }
    if (listen !== undefined && !isValidAddress(listen)) {
      throw new RangeError('listen must be a valid address or omitted');
    }
    this.listen = listen;
    this.capacity = capacity;
    this.timeoutMs = timeoutMs;
  }

  has(address: string): boolean {
    return this.entries.has(address);
  }

  get size(): number {
    return this.entries.size;
  }

  addresses(): string[] {
    return [...this.entries.keys()];
  }

  lastSeen(address: string): number | undefined {
    return this.entries.get(address);
  }

  insert(address: string, nowMs: number): boolean {
    return this.put(address, nowMs, true);
  }

  ingest(addresses: readonly string[], nowMs: number, solicited: boolean): number {
    if (!solicited) return 0;
    let added = 0;
    for (const address of addresses) {
      if (this.put(address, nowMs, false)) added += 1;
    }
    return added;
  }

  advertise(): string[] {
    return [...this.entries.keys()].sort((a, b) => {
      if (a < b) return -1;
      if (a > b) return 1;
      return 0;
    });
  }

  sweep(nowMs: number): number {
    const expired: string[] = [];
    for (const [address, seen] of this.entries) {
      if (nowMs - seen > this.timeoutMs) expired.push(address);
    }
    for (const address of expired) {
      this.entries.delete(address);
      this.solicited.delete(address);
    }
    return expired.length;
  }

  markSolicited(peer: string): boolean {
    if (!isValidAddress(peer)) return false;
    this.solicited.add(peer);
    return true;
  }

  isSolicited(peer: string): boolean {
    return this.solicited.has(peer);
  }

  clearSolicited(peer: string): void {
    this.solicited.delete(peer);
  }

  private put(address: string, nowMs: number, evict: boolean): boolean {
    if (!isValidAddress(address) || address === this.listen) return false;
    if (this.entries.has(address)) {
      this.entries.set(address, nowMs);
      return false;
    }
    if (this.entries.size >= this.capacity) {
      if (!evict) return false;
      const oldest = this.entries.keys().next();
      if (!oldest.done) {
        this.entries.delete(oldest.value);
        this.solicited.delete(oldest.value);
      }
    }
    this.entries.set(address, nowMs);
    return true;
  }
}

export class LocalDiscovery {
  readonly book: AddressBook;
  readonly enabled: boolean;

  constructor(book: AddressBook, enabled: boolean = true) {
    this.book = book;
    this.enabled = enabled;
  }

  request(peer: string): boolean {
    if (!this.enabled) return false;
    return this.book.markSolicited(peer);
  }

  reply(): string[] | null {
    if (!this.enabled) return null;
    return this.book.advertise();
  }

  accept(fromPeer: string, addresses: readonly string[], nowMs: number): number {
    if (!this.enabled || !this.book.isSolicited(fromPeer)) return 0;
    this.book.clearSolicited(fromPeer);
    return this.book.ingest(addresses, nowMs, true);
  }
}
