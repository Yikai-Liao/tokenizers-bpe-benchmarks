// Benchmark reference: each token has an independently owned map key and ID string.
struct DualStrings {
    by_text: AHashMap<CompactString, usize>,
    by_id: Vec<CompactString>,
}
impl DualStrings {
    fn with_capacity_and_hasher(capacity: usize, hasher: RandomState) -> Self {
        Self {
            by_text: AHashMap::with_capacity_and_hasher(capacity, hasher),
            by_id: Vec::with_capacity(capacity),
        }
    }
    fn len(&self) -> usize { self.by_id.len() }
    fn get_index_of(&self, text: &str) -> Option<usize> { self.by_text.get(text).copied() }
    fn insert_full(&mut self, text: CompactString) -> (usize, bool) {
        if let Some(id) = self.get_index_of(text.as_str()) { return (id, false); }
        let id = self.by_id.len();
        self.by_text.insert(text.clone(), id);
        self.by_id.push(text);
        (id, true)
    }
    fn iter(&self) -> std::slice::Iter<'_, CompactString> { self.by_id.iter() }
}
impl Index<usize> for DualStrings {
    type Output = CompactString;
    fn index(&self, id: usize) -> &Self::Output { &self.by_id[id] }
}
impl IntoIterator for DualStrings {
    type Item = CompactString;
    type IntoIter = std::vec::IntoIter<CompactString>;
    fn into_iter(self) -> Self::IntoIter { self.by_id.into_iter() }
}
