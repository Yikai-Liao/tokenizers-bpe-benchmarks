//! Benchmark reference for SortedPositions: full U64 values instead of G128.
//! The handle, inline cases, allocation lease and atomic publication contract
//! remain the same. This module is generated into an isolated source snapshot.
use crate::{AllocationLease, Result, StorageError};
use std::alloc::{Layout, alloc, dealloc};
use std::collections::BinaryHeap;
use std::marker::PhantomData;
use std::ops::Range;

const _: () = assert!(usize::BITS == 64);
const INLINE: usize = 1 << 63;
const PAIR: usize = 1 << 62;
const DELTA_MASK: usize = PAIR - 1;

#[derive(Default)]
pub struct PositionEncodingScratch { _reserved: () }

#[derive(Default)]
pub struct SortedPositions<'a> {
    count_and_flags: usize,
    payload: *mut u64,
    arena_lifetime: PhantomData<&'a crate::AllocationArena>,
}
// SAFETY: an owned heap allocation or immutable borrowed arena storage moves
// with the handle. Mutation requires exclusive access and the arena outlives it.
unsafe impl Send for SortedPositions<'_> {}
// SAFETY: shared readers only access the published initialized prefix.
unsafe impl Sync for SortedPositions<'_> {}
const _: () = assert!(std::mem::size_of::<SortedPositions<'_>>() == 16);

fn allocation_layout(capacity: usize) -> Result<Layout> {
    let bytes = capacity.checked_mul(8).and_then(|n| n.checked_add(8))
        .ok_or(StorageError("position allocation size overflow"))?;
    Layout::from_size_align(bytes, 8)
        .map_err(|_| StorageError("position allocation exceeds resident bounds"))
}
fn reverse_run(
    count: usize, minimum: u64, mut input: impl Iterator<Item = u64>,
    mut visit: impl FnMut(usize, u64),
) -> Result<()> {
    let mut previous = None;
    for index in (0..count).rev() {
        let value = input.next().ok_or(StorageError("position run ended early"))?;
        if value < minimum || previous.is_some_and(|last| value > last) {
            return Err(StorageError("positions are not sorted"));
        }
        visit(index, value);
        previous = Some(value);
    }
    if input.next().is_some() { return Err(StorageError("position run exceeds its declared length")); }
    Ok(())
}
impl<'a> SortedPositions<'a> {
    pub fn new() -> Self { Self::default() }
    pub fn len(&self) -> usize {
        if self.count_and_flags & INLINE == 0 { self.count_and_flags }
        else if self.count_and_flags & PAIR == 0 { 1 } else { 2 }
    }
    pub fn is_empty(&self) -> bool { self.len() == 0 }
    fn is_inline(&self) -> bool { self.is_empty() || self.count_and_flags & INLINE != 0 }
    fn capacity(&self) -> usize {
        // SAFETY: non-inline handles point at their initialized allocation header.
        unsafe { (self.payload.read() >> 1) as usize }
    }
    fn arena_allocated(&self) -> bool {
        if self.is_inline() { return false; }
        // SAFETY: same initialized header as capacity().
        unsafe { self.payload.read() & 1 != 0 }
    }
    fn allocate(count: usize, capacity: usize, lease: &AllocationLease<'a>) -> Result<Self> {
        if count >= INLINE || capacity < count { return Err(StorageError("position count exceeds resident bounds")); }
        let layout = allocation_layout(capacity)?;
        let (pointer, arena) = match lease.allocate(layout)? {
            Some(pointer) => (pointer.as_ptr().cast::<u64>(), true),
            None => {
                // SAFETY: layout is nonzero and validated above. The owner frees
                // this exact layout unless ownership moves to another handle.
                let pointer = unsafe { alloc(layout) }.cast::<u64>();
                if pointer.is_null() { return Err(StorageError("position heap allocation failed")); }
                (pointer, false)
            }
        };
        // SAFETY: the header is aligned and writable; the payload is unpublished.
        unsafe { pointer.write((capacity as u64) << 1 | u64::from(arena)); }
        Ok(Self { count_and_flags: count, payload: pointer, arena_lifetime: PhantomData })
    }
    fn build(count: usize, mut input: impl Iterator<Item = u64>,
             _scratch: &mut PositionEncodingScratch, lease: &AllocationLease<'a>) -> Result<Self> {
        if count == 0 {
            if input.next().is_some() { return Err(StorageError("position run exceeds its declared length")); }
            return Ok(Self::new());
        }
        if count <= 2 {
            let last = input.next().ok_or(StorageError("position run ended early"))?;
            let first = if count == 1 { last }
                else { input.next().ok_or(StorageError("position run ended early"))? };
            if input.next().is_some() { return Err(StorageError("position run exceeds its declared length")); }
            let gap = last.checked_sub(first).ok_or(StorageError("positions are not sorted"))?;
            if count == 1 || gap <= DELTA_MASK as u64 {
                return Ok(Self {
                    count_and_flags: INLINE | if count == 2 { PAIR | gap as usize } else { 0 },
                    payload: std::ptr::without_provenance_mut(first as usize), arena_lifetime: PhantomData,
                });
            }
            let result = Self::allocate(count, count, lease)?;
            // SAFETY: both payload elements are inside the allocated capacity.
            unsafe { result.payload.add(1).write(first); result.payload.add(2).write(last); }
            return Ok(result);
        }
        let result = Self::allocate(count, count, lease)?;
        reverse_run(count, 0, input, |index, value| {
            // SAFETY: each element is written once inside the unpublished capacity.
            unsafe { result.payload.add(1 + index).write(value); }
        })?;
        Ok(result)
    }
    pub fn from_reversed_iter(count: usize, input: impl Iterator<Item = u64>,
                              scratch: &mut PositionEncodingScratch, lease: &AllocationLease<'a>) -> Result<Self> {
        Self::build(count, input, scratch, lease)
    }
    pub fn from_sorted_iter(input: impl DoubleEndedIterator<Item = u64> + ExactSizeIterator,
                            scratch: &mut PositionEncodingScratch, lease: &AllocationLease<'a>) -> Result<Self> {
        Self::build(input.len(), input.rev(), scratch, lease)
    }
    pub fn from_sorted(values: &[u64], scratch: &mut PositionEncodingScratch,
                       lease: &AllocationLease<'a>) -> Result<Self> {
        Self::from_sorted_iter(values.iter().copied(), scratch, lease)
    }
    pub fn from_chain(chains: &crate::PositionChains, chain: crate::PositionChain,
                      scratch: &mut PositionEncodingScratch, lease: &AllocationLease<'a>) -> Result<Self> {
        Self::build(chain.len(), chains.reversed(chain), scratch, lease)
    }
    // INSERT_CHAIN_METHODS
    pub fn append_chain(&mut self, chains: &crate::PositionChains, chain: crate::PositionChain,
                        scratch: &mut PositionEncodingScratch, lease: &AllocationLease<'a>) -> Result<()> {
        self.append_reverse(chain.len(), chains.reversed(chain), scratch, lease)
    }
    pub fn append_sorted_iter(&mut self, input: impl DoubleEndedIterator<Item = u64> + ExactSizeIterator + Clone,
                              scratch: &mut PositionEncodingScratch, lease: &AllocationLease<'a>) -> Result<()> {
        self.append_reverse(input.len(), input.rev(), scratch, lease)
    }
    pub fn append_sorted(&mut self, values: &[u64], scratch: &mut PositionEncodingScratch,
                         lease: &AllocationLease<'a>) -> Result<()> {
        self.append_sorted_iter(values.iter().copied(), scratch, lease)
    }
    pub fn append(&mut self, other: Self, scratch: &mut PositionEncodingScratch,
                  lease: &AllocationLease<'a>) -> Result<()> {
        if self.is_empty() { *self = other; return Ok(()); }
        self.append_sorted_iter(other.iter(), scratch, lease)
    }
    fn append_reverse(&mut self, count: usize, input: impl Iterator<Item = u64> + Clone,
                      scratch: &mut PositionEncodingScratch, lease: &AllocationLease<'a>) -> Result<()> {
        if count == 0 { return Ok(()); }
        let old_len = self.len();
        let end = old_len.checked_add(count).filter(|&n| n < INLINE)
            .ok_or(StorageError("position count exceeds resident bounds"))?;
        if self.is_inline() {
            let mut old = [0; 2];
            self.iter().decode_into(&mut old[..old_len]);
            let result = Self::build(end, input.chain(old[..old_len].iter().rev().copied()), scratch, lease)?;
            *self = result;
            return Ok(());
        }
        let minimum = self.get(old_len - 1);
        reverse_run(count, minimum, input.clone(), |_, _| {})?;
        if end <= self.capacity() {
            reverse_run(count, minimum, input, |index, value| {
                // SAFETY: these spare suffix slots do not overlap the readable prefix.
                unsafe { self.payload.add(1 + old_len + index).write(value); }
            })?;
            // Replay and validation succeeded; publish the complete suffix now.
            self.count_and_flags = end;
            return Ok(());
        }
        let capacity = end.max(self.capacity().saturating_mul(2));
        let mut result = Self::allocate(end, capacity, lease)?;
        // SAFETY: allocations are disjoint, and both have old_len initialized slots.
        unsafe { std::ptr::copy_nonoverlapping(self.payload.add(1), result.payload.add(1), old_len); }
        reverse_run(count, minimum, input, |index, value| {
            // SAFETY: checked capacity contains the entire unpublished suffix.
            unsafe { result.payload.add(1 + old_len + index).write(value); }
        })?;
        std::mem::swap(self, &mut result);
        Ok(())
    }
    fn get(&self, index: usize) -> u64 {
        assert!(index < self.len());
        if self.is_inline() {
            let first = self.payload.addr() as u64;
            return first + if index == 0 { 0 } else { (self.count_and_flags & DELTA_MASK) as u64 };
        }
        // SAFETY: only elements in the published initialized prefix are read.
        unsafe { self.payload.add(1 + index).read() }
    }
    pub fn lower_bound(&self, position: u64) -> usize {
        let (mut low, mut high) = (0, self.len());
        while low < high {
            let middle = low + (high - low) / 2;
            if self.get(middle) < position { low = middle + 1; } else { high = middle; }
        }
        low
    }
    pub fn cursor(&self, range: Range<usize>) -> PositionCursor<'_, 'a> {
        assert!(range.start <= range.end && range.end <= self.len());
        PositionCursor { list: self, range }
    }
    pub fn iter(&self) -> PositionCursor<'_, 'a> { self.cursor(0..self.len()) }
}
// INSERT_DESCENDING_MERGE
#[derive(Clone)]
pub struct PositionCursor<'list, 'arena> {
    list: &'list SortedPositions<'arena>, range: Range<usize>,
}
impl PositionCursor<'_, '_> {
    pub fn decode_into(&mut self, output: &mut [u64]) -> usize {
        let count = output.len().min(self.len());
        for value in &mut output[..count] { *value = self.next().unwrap(); }
        count
    }
}
impl Iterator for PositionCursor<'_, '_> {
    type Item = u64;
    #[inline]
    fn next(&mut self) -> Option<u64> { self.range.next().map(|index| self.list.get(index)) }
    fn size_hint(&self) -> (usize, Option<usize>) { let n = self.range.len(); (n, Some(n)) }
}
impl DoubleEndedIterator for PositionCursor<'_, '_> {
    fn next_back(&mut self) -> Option<u64> { self.range.next_back().map(|index| self.list.get(index)) }
}
impl ExactSizeIterator for PositionCursor<'_, '_> {}
impl std::iter::FusedIterator for PositionCursor<'_, '_> {}
impl Drop for SortedPositions<'_> {
    fn drop(&mut self) {
        if !self.is_inline() && !self.arena_allocated() {
            let layout = allocation_layout(self.capacity()).expect("validated position allocation layout");
            // SAFETY: this owner holds the exact heap pointer/layout and releases it once.
            unsafe { dealloc(self.payload.cast(), layout); }
        }
    }
}
// INSERT_BEHAVIORAL_TESTS
