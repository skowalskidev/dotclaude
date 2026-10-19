# Source from .zshenv, and after PATH setup in .zprofile and .zshrc.
# Login shells run path_helper after .zshenv; reapply the same selection afterward.
() {
  emulate -L zsh
  local node_root="${NVM_DIR:-$HOME/.nvm}/versions/node"
  local node_path
  local -a candidates
  candidates=("$node_root"/v24.<->.<->/bin(Nn))
  for node_path in ${(Oa)candidates}; do
    [[ -x "$node_path/node" && -f "$node_path/npm" && -f "$node_path/npx" ]] || continue
    path=("$node_path" ${path:#${(b)node_path}})
    export PATH NVM_BIN="$node_path" NVM_INC="${node_path:h}/include/node"
    return 0
  done
  print -u2 'Node 24 is missing from nvm. Install it with nvm install 24.'
  return 1
}
