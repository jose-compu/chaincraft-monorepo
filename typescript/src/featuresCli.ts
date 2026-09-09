/**
 * Prints the feature manifest as JSON on stdout.
 *
 * tools/parity_check.py parses this, so nothing else may reach stdout.
 * Diagnostics go to stderr.
 */

import { manifest } from './features.ts';

process.stdout.write(`${JSON.stringify(manifest(), null, 2)}\n`);
