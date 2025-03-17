# myo-vr

#### WIP

Added classifier with random forest:
1. Start by entering your MYO UUID and MAC address in the config.json file
2. use data-collection.py to collect poses data, you will have to enter how many seconds and what pose is it
3. use preprocessing.py to split raw data 
4. run train.py to train the model 
5. run classifier.py to connect to myo and interpret your gesture at runtime
