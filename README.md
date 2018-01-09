# Directory Structure

coq, mathcomp-1.6.1, and mathcomp-odd-order-1.6.1 come from different repos.

```
+ tcoq (modified version of coq)

+ odd-order (feit-thompson)
+ math-comp (ssreflect stuff)

+ ex (example coq tactic scripts and their corresponding traces) 
+ notes (notes for ourselves)
+ utils (right now, python tools for working with the data)
```


# Initial Setup

1. Get the data script.
   ```
   ./get_data.sh
   ```
   This gets tcoq, math-comp, and odd-order.


# Build

Build dataset:
1. Configure coq first.
   ```
   ./setup_tcoq.sh
   ```
2. Build everything
   ```
   . ./build_all.sh
   ```

Step 2 above can be broken down into:
1. Build coq next.
   ```
   ./build_tcoq.sh
   ```
2. IMPORTANT: set your terminal to point to the built version of coq
   ```
   source myconfig.sh
   ```
3. Build mathematical components and Feit-Thompson
   ```
   ./build_mathcomp.sh; ./build_oddorder.sh
   ```



# Recurrent Building

1. Get latest changes
   ```
   git submodule update --remote --merge
   ```
2. Build (takes like 2.5 hours)
   ```
   ./build_all.sh
   ```


# Usage

* To begin, run 'chunk.py` to break up the odd-order's build.log
   ```
   python utils/chunk.py <path-to-odd-order-build.log> <output-directory>
   ```
   We recommend having a top-level `data` folder and setting `<output-directory> = data/odd-order`.

* You you can use 'visualize.py` to visualize the tactic traces. This will attempt to reconstruct the tactic traces and record relevant statistics. Here are some example invocations:
   1. Visualize a file, saving raw tactic (before attempting to reconstruct trace) statistics to `log/rawtac.log` and outputing reconstruction statistics to `log/recon.log`. Omitting `-s` and/or `-o` means that these logs will be written to `./rawtac.log` and `./recon.log` respectively.
      ```
      python utils/visualize.py data/odd-order/BGsection1.v.dump -s log/rawtac.log -o log/recon.log
      ```
   2. Visualize the lemma `minnormal_solvable_Fitting_center` within the file and display (`-d`) the tactic trace.
      ```
      python utils/visualize.py data/odd-order/BGsection1.v.dump -l minnormal_solvable_Fitting_center -d
      ``` 
 
TODO(deh): reconstruct tactics. The number of connected components should be 1 if the tree has been successfully reconstructed.


# Other

TODO(deh): missing requirements.txt
