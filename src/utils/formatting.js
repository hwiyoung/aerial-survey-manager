/**
 * Shared formatting utilities.
 */

/**
 * Format bytes to a human-readable string with unit (e.g. "1.23 GB").
 * Automatically selects the most appropriate unit (B, KB, MB, GB, TB).
 */
export function formatBytes(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Format bytes returning only the numeric value (without unit).
 * Used for dashboard stats cards where value and unit are displayed separately.
 *
 *   formatBytesValue(1.5 * 1024**4) => "1.5"
 */
export function formatBytesValue(bytes) {
    if (!bytes || bytes <= 0) return '0';
    const tb = bytes / (1024 ** 4);
    if (tb >= 1) return tb.toFixed(1);
    const gb = bytes / (1024 ** 3);
    return gb.toFixed(1);
}

/**
 * Return the best unit string for the given byte count (GB or TB).
 * Companion to formatBytesValue.
 */
export function formatBytesUnit(bytes) {
    if (!bytes || bytes <= 0) return 'GB';
    const tb = bytes / (1024 ** 4);
    return tb >= 1 ? 'TB' : 'GB';
}

/**
 * Format speed (bytes/sec) to human-readable string.
 */
export function formatSpeed(bytesPerSecond) {
    return formatBytes(bytesPerSecond) + '/s';
}
