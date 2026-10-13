// TypeScript parser: comments / strings / JSX text are never treated as API calls.
const fs = require('fs');
const path = require('path');
const ts = require(process.argv[2]);
const root = path.resolve(process.argv[3]);
const entry = process.argv[4];
const hits = [], seen = new Set(), parseErrors = [];
function access(node, owner, member) {
  return (ts.isPropertyAccessExpression(node) && node.expression.getText() === owner && node.name.text === member) ||
    (ts.isElementAccessExpression(node) && node.expression.getText() === owner && ts.isStringLiteral(node.argumentExpression) && node.argumentExpression.text === member);
}
function visitFile(file) {
  file = path.resolve(file);
  if (seen.has(file) || !file.startsWith(root + path.sep) || !fs.existsSync(file)) return;
  seen.add(file);
  const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true);
  for (const d of source.parseDiagnostics) parseErrors.push(`${path.relative(root, file)}: ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`);
  function visit(node) {
    let label;
    if (ts.isCallExpression(node)) {
      if (access(node.expression, 'Math', 'random')) label = 'Math.random';
      if (access(node.expression, 'Date', 'now')) label = 'Date.now';
    }
    if (ts.isNewExpression(node) && node.expression.getText(source) === 'Date' && (!node.arguments || node.arguments.length === 0)) label = 'new Date()';
    if (label) hits.push(`${path.relative(root, file).replaceAll('\\', '/')}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}:${label}`);
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      const name = node.moduleSpecifier.text;
      if (name.startsWith('.')) {
        const resolved = ts.resolveModuleName(name, file, {jsx: ts.JsxEmit.React, allowJs: true, moduleResolution: ts.ModuleResolutionKind.NodeJs}, ts.sys).resolvedModule;
        if (resolved) visitFile(resolved.resolvedFileName);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
visitFile(path.join(root, entry));
if (!seen.size) parseErrors.push('入口文件不存在');
process.stdout.write(JSON.stringify({hits, parseErrors, files: [...seen].map(f => path.relative(root, f))}));
