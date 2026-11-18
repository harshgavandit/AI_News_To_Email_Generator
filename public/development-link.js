export function developmentLink(id) {
  return /^[a-f0-9]{32}$/.test(id || "") ? `/development.html?id=${id}` : "";
}
