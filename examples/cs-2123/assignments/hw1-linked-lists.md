---
title: "HW1: Linked Lists"
due: 2026-09-07T23:59
posted: 2026-08-24
source: "https://lms.example.edu/ultra/courses/_00000_1/outline/assignment/_00002_1"
status: open
todoist_task_id: ""
---

Implement a singly linked list of integers in `list.c` against the header you
were given. Do not change `list.h`.

Required operations:

- `list_push_front(list, value)`: constant time.
- `list_delete(list, value)`: remove the first node holding that value and
  return whether anything was removed.
- `list_length(list)`: number of nodes.
- `list_free(list)`: release every node.

Requirements:

1. No arrays and no library list type. Nodes and pointers only.
2. Deleting the head, deleting the only element, and deleting from an empty list
   all have to work. Half the test cases are these.
3. `make test` passes with no leaks under the memory checker.
4. Write two or three sentences in `notes.md` on why insertion at the front is
   cheaper than insertion in the middle.

Turn in `list.c` and `notes.md`. See the 08-24 and 08-26 lectures.
