export type VisualizationExample = {
  id: string;
  title: string;
  topic: string;
  description: string;
  focus: string;
  source: string;
};
export const visualizationExamples: VisualizationExample[] = [
  {
    id: "for",
    title: "A running total",
    topic: "For loops",
    description: "Watch each iteration update the same variable.",
    focus: "Follow total as the loop visits each number.",
    source: `numbers = [2, 4, 6]
total = 0
for number in numbers:
    total += number
print(total)`,
  },
  {
    id: "while",
    title: "Count down",
    topic: "While loops",
    description: "See the condition checked before each pass.",
    focus: "When does remaining stop satisfying the condition?",
    source: `remaining = 3
while remaining > 0:
    print(remaining)
    remaining -= 1
print("Launch!")`,
  },
  {
    id: "conditions",
    title: "Choose a branch",
    topic: "Conditions",
    description: "Trace if, elif, and else with different inputs.",
    focus: "Change temperature, then build a new trace to compare the path.",
    source: `temperature = 18
raining = True
if temperature < 10:
    outfit = "Coat"
elif raining:
    outfit = "Rain jacket"
else:
    outfit = "T-shirt"
print(outfit)`,
  },
  {
    id: "lists",
    title: "Two names, one list",
    topic: "Lists",
    description: "Understand mutation, aliases, and a separate copy.",
    focus: "Notice that original and alias point to the same object.",
    source: `original = [10, 20, 30]
alias = original
copy = original[:]
alias.append(40)
copy[0] = 99
print(original)
print(copy)`,
  },
  {
    id: "dicts",
    title: "Count the words",
    topic: "Dictionaries",
    description: "Build a frequency table one word at a time.",
    focus: "Watch keys appear, then their counts change.",
    source: `words = ["duck", "code", "duck", "learn"]
counts = {}
for word in words:
    if word not in counts:
        counts[word] = 0
    counts[word] += 1
print(counts)`,
  },
  {
    id: "tuples",
    title: "Coordinates and unpacking",
    topic: "Tuples",
    description: "Group values, unpack them, and create a new tuple.",
    focus:
      "A new coordinate creates a new tuple rather than changing the old one.",
    source: `point = (3, 4)
x, y = point
distance_squared = x * x + y * y
moved = (x + 1, y + 2)
print(point)
print(moved)
print(distance_squared)`,
  },
  {
    id: "functions",
    title: "A function call",
    topic: "Functions",
    description: "See arguments enter a frame and a return value leave it.",
    focus: "The function has its own variables, separate from the module.",
    source: `def double(number):
    result = number * 2
    return result

value = 7
answer = double(value)
print(answer)`,
  },
  {
    id: "oop",
    title: "Objects with state",
    topic: "Objects & classes",
    description: "Create two instances and call a method on one.",
    focus: "Track self back to the object whose state it changes.",
    source: `class Counter:
    def __init__(self, start):
        self.value = start

    def increment(self):
        self.value += 1
        return self.value

first = Counter(0)
second = Counter(10)
first.increment()
print(first.value, second.value)`,
  },
  {
    id: "search",
    title: "Binary search",
    topic: "Algorithms",
    description: "Watch the search interval narrow until it finds a value.",
    focus: "Compare low, high, and mid at each step.",
    source: `numbers = [2, 5, 8, 12, 16, 23, 38]
target = 16
low = 0
high = len(numbers) - 1
found = -1
while low <= high:
    mid = (low + high) // 2
    if numbers[mid] == target:
        found = mid
        break
    elif numbers[mid] < target:
        low = mid + 1
    else:
        high = mid - 1
print(found)`,
  },
  {
    id: "sort",
    title: "Insertion sort",
    topic: "Algorithms",
    description: "Move each value into the sorted portion of a list.",
    focus: "Follow the key and watch larger values shift to the right.",
    source: `numbers = [4, 2, 5, 1]
for index in range(1, len(numbers)):
    key = numbers[index]
    previous = index - 1
    while previous >= 0 and numbers[previous] > key:
        numbers[previous + 1] = numbers[previous]
        previous -= 1
    numbers[previous + 1] = key
print(numbers)`,
  },
  {
    id: "recursion",
    title: "Factorial, one call at a time",
    topic: "Recursion",
    description: "Follow calls down to the base case, then watch them return.",
    focus: "Each call keeps its own n until the smaller call finishes.",
    source: `def factorial(n):
    if n <= 1:
        return 1
    smaller = factorial(n - 1)
    return n * smaller

answer = factorial(4)
print(answer)`,
  },
];
