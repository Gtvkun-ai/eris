// esbuild.js — build script cho Eris VS Code extension
// Bundle extension host code into one VS Code-compatible CommonJS entrypoint.
// esbuild bundle ESM dependencies vào CJS output mà VS Code Extension Host cần.

const esbuild = require('esbuild');
const path = require('path');

const isWatch = process.argv.includes('--watch');
const isProd = process.argv.includes('--production');

/** @type {import('esbuild').BuildOptions} */
const buildOptions = {
  entryPoints: [path.join(__dirname, 'src', 'extension.ts')],
  bundle: true,
  outfile: path.join(__dirname, 'dist', 'extension.js'),

  // VS Code Extension Host chạy CommonJS; esbuild sẽ bundle ESM deps vào đây.
  format: 'cjs',
  platform: 'node',
  target: 'node22',

  // vscode là built-in của Extension Host, không bundle vào.
  external: ['vscode'],

  sourcemap: !isProd,
  minify: isProd,

  // Log build errors rõ ràng
  logLevel: 'info',
};

async function main() {
  if (isWatch) {
    const ctx = await esbuild.context(buildOptions);
    await ctx.watch();
    console.log('[esbuild] watching for changes...');
  } else {
    await esbuild.build(buildOptions);
    console.log('[esbuild] build complete →', buildOptions.outfile);
  }
}

main().catch((err) => {
  console.error('[esbuild] build failed:', err);
  process.exit(1);
});
